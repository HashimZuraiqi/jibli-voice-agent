"""Careem services through MCP (careem-mcp: groceries, food, cart, Box, user) plus a local rides stand-in.

The LLM sees Careem's real tool definitions, except the three that spend money. To pay, it proposes the exact
checkout call with request_confirmation; this code runs it only after the user's clear yes or the family's approval.
"""
import datetime as dt
import json
import math
import os
import uuid

from jsonschema import Draft202012Validator

from .careem_mcp import CHECKOUT_OFF, checkout_allowed, is_production
from .personalization import guardrails as g
from .personalization.repurchase import predictions

MCP_URL = os.getenv("CAREEM_MCP_URL") or "http://127.0.0.1:8787/mcp"  # the local sandbox by default

# what the LLM may call directly (read, search, build carts and quotes)
LLM_TOOLS = [
    "user_info", "get_activities", "track_activity", "reverse_geocode",
    "search_groceries_get_top_user_items", "search_groceries_items", "search_groceries_get_all_deals",
    "create_grocery_cart_with_quantities", "cart_get_quik_basket",
    "food_merchant_search", "food_dish_search", "food_get_restaurant_menu", "food_get_item_options", "cart_add_items",
    "cart_get_basket", "cart_get_basket_price", "cart_get_checkout_promos", "cart_update_item", "cart_delete_items",
    "box_get_config", "box_get_categories", "box_get_vehicle_types", "box_pre_checkout",
]
# what spends money: never given to the LLM, only run after a confirmation (rides_request is the local stand-in)
SPENDING = {"cart_grocery_checkout": "groceries", "cart_checkout": "food", "box_create_order": "box", "rides_request": "ride"}
# a new cart or quote makes an earlier confirmation for the same service stale (carts are shared by groceries and food)
CHANGES_ORDER = {"create_grocery_cart_with_quantities": {"groceries", "food"}, "cart_add_items": {"groceries", "food"},
                 "cart_add_item": {"groceries", "food"}, "cart_update_item": {"groceries", "food"},
                 "cart_delete_items": {"groceries", "food"}, "cart_delete_basket": {"groceries", "food"},
                 "cart_reorder": {"groceries", "food"}, "box_pre_checkout": {"box"}, "rides_get_quote": {"ride"}}

# a Box checkout must match its quote on all of these; quotes older than this are priced again
BOX_BINDING = ("cct_id", "pickup_location_id", "dropoff_location_id", "pickup_latitude", "pickup_longitude")
QUOTE_MAX_AGE = dt.timedelta(minutes=30)

# rides are not in Careem's public MCP sandbox yet: a small local stand-in with the same confirm-then-pay flow
RIDE_PRODUCTS = {"Go": (8.0, 1.9), "Comfort": (11.0, 2.4), "Business": (25.0, 4.1)}  # base AED, AED per km


class CareemMCP:
    """Careem's MCP connection (careem_mcp.MCPConnector: http or sse, Bearer token for production), tools cached by name."""

    def __init__(self, url=None):
        from .careem_mcp import MCPConnector
        self.conn = MCPConnector(url or MCP_URL)
        self._tools = None

    def tools(self):
        if self._tools is None:
            self._tools = {t["name"]: t for t in self.conn.list_tools()}
        return self._tools

    def call(self, name, args):
        return self.conn.call(name, args)


def _km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a["latitude"], a["longitude"], b["latitude"], b["longitude"]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def _positive(x):
    """A real, finite price above zero (NaN, inf, negatives and text fail closed)."""
    try:
        return math.isfinite(float(x)) and float(x) > 0
    except (TypeError, ValueError):
        return False


def _find(obj, keys):
    """The first value under any of `keys`, anywhere in a nested Careem answer."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in keys and not isinstance(v, (dict, list)):
                return v
        obj = list(obj.values())
    if isinstance(obj, list):
        for v in obj:
            found = _find(v, keys)
            if found is not None:
                return found
    return None


def _compact(result, limit=6000):
    """Careem results can be large; the LLM gets at most `limit` characters."""
    text = json.dumps(result, ensure_ascii=False)
    return result if len(text) <= limit else {"truncated": True, "json": text[:limit]}


class CareemTools:
    def __init__(self, store, memory, places, mcp=None):
        self.store, self.memory, self.places = store, memory, places
        self.mcp = mcp or CareemMCP()
        # rides here are a local stand-in: never on the real Careem account, where it would fake a booking
        self.rides = not is_production(self.mcp.conn.url)

    # ---------- what the LLM sees ----------
    def schemas(self):
        defs = self.mcp.tools()
        out = []
        for name in LLM_TOOLS:
            d = defs[name]
            params = {k: v for k, v in d["inputSchema"].items() if k != "$schema"}
            out.append({"type": "function", "function": {"name": name, "description": d.get("description", "")[:900],
                                                         "parameters": params}})
        S = {"type": "string"}
        spending = [t for t in SPENDING if self.rides or t != "rides_request"]
        local = [
            ("rides_get_quote", "Price a Careem ride between two saved places (labels like Home, Work, Gym, Dubai Mall, Airport T3).",
             {"pickup": S, "dropoff": S, "product": {"type": "string", "enum": list(RIDE_PRODUCTS)}}, ["pickup", "dropoff"]),
            ("usual_basket", "The user's usual grocery items with days since each was last bought and whether it is running out.", {}, []),
            ("request_confirmation",
             "Before anything is ordered or booked: propose the exact checkout call and ask the user (by='user') or the family "
             "member who confirms. checkout_tool is one of cart_grocery_checkout, cart_checkout, box_create_order, rides_request; "
             "checkout_args are its exact arguments (for rides_request: the quote_id from rides_get_quote); total is the price.",
             {"by": S, "checkout_tool": {"type": "string", "enum": spending}, "checkout_args": {"type": "object"},
              "total": {"type": "number"}, "currency": S, "summary": S},
             ["by", "checkout_tool", "checkout_args", "total", "summary"]),
            ("place_order", "Run the confirmed checkout after the USER said yes to request_confirmation(by='user'). "
             "Family members approve in their own app, never here.", {"confirmed_by": S}, ["confirmed_by"]),
            ("memory_list", "Everything remembered about the user (answer 'what do you know about me?').", {}, []),
            ("memory_forget", "Delete one remembered fact by id, or everything when memory_id is 'all'.", {"memory_id": S}, ["memory_id"]),
        ]
        out += [{"type": "function", "function": {"name": n, "description": d,
                                                        "parameters": {"type": "object", "properties": p, "required": r}}}
                for n, d, p, r in local if self.rides or n != "rides_get_quote"]
        out[-4]["function"]["description"] += " Arguments per checkout_tool: " + self.checkout_fields()
        return out

    def checkout_fields(self):
        """Required and optional argument names of each checkout tool, so the model gets them right the first time."""
        parts = ["rides_request(required: quote_id, product)"]
        for tool in ("cart_grocery_checkout", "cart_checkout", "box_create_order"):
            sch = self.mcp.tools()[tool]["inputSchema"]
            req = sch.get("required", [])
            opt = [k for k in sch.get("properties", {}) if k not in req]
            parts.append(f"{tool}(required: {', '.join(req)}; optional: {', '.join(opt)})")
        return "; ".join(parts) + ". Use payment_type cash unless the user chose another way to pay."

    def run(self, name, args, ctx):
        uid = ctx["user_id"]
        pending = self.store.state["pending"].get(uid)
        if pending and SPENDING.get(pending.get("tool")) in CHANGES_ORDER.get(name, ()):
            self.store.state["pending"].pop(uid)  # that service's cart or quote changed after confirmation was requested
            self.store.save()
        local = getattr(self, "t_" + name, None)
        if local:
            try:
                return local(ctx, **args)
            except TypeError as e:
                return {"error": f"bad arguments: {e}"}
        if name in SPENDING:
            return {"error": f"BLOCKED by guardrail: {name} runs only after confirmation; use request_confirmation"}
        if name not in LLM_TOOLS:
            return {"error": f"unknown tool {name}"}
        try:
            result = self.mcp.call(name, args)
        except Exception as e:  # Careem unreachable: tell the model, keep the conversation alive
            return {"error": f"Careem service unavailable: {type(e).__name__}: {str(e)[:200]}"}
        self._remember_prices(uid, name, args, result)
        return _compact(result)

    def _remember_prices(self, uid, name, args, result):
        """Keep what Careem said things cost, so the spend cap never depends on a number the LLM typed."""
        prices = self.store.state.setdefault("careem_prices", {}).setdefault(uid, {})
        if CHANGES_ORDER.get(name, set()) & {"groceries", "food"}:
            prices.pop("baskets", None)  # a changed cart must be priced again
        if not isinstance(result, dict) or result.get("error"):
            self.store.save()
            return
        if name == "box_pre_checkout" and isinstance(result.get("delivery_estimate"), dict):
            est = result["delivery_estimate"]
            prices["box"] = {"ts": dt.datetime.now().isoformat(timespec="seconds"), "max_price": est.get("max_price"),
                             "currency": est.get("currency_code"),
                             **{k: result.get(k, args.get(k)) for k in BOX_BINDING}}
        found = _find(result, ("currency_code", "currency"))
        if name.startswith(("cart_", "create_grocery")) and isinstance(found, str):
            prices["cart_currency"] = found  # Careem's cart answers name the currency; the price answer may not
        if name == "cart_get_basket_price":
            basket, price = result.get("basket") or {}, (result.get("price") or {}).get("price") or {}
            currency = found if isinstance(found, str) else prices.get("cart_currency")
            if basket.get("id") is not None and isinstance(price.get("total"), (int, float)) and isinstance(currency, str):
                prices.setdefault("baskets", {})[str(basket["id"])] = {"total": float(price["total"]), "currency": currency.upper()}
        self.store.save()

    # ---------- local tools ----------
    def t_usual_basket(self, ctx):
        return {"items": [{k: p[k] for k in ("name_en", "name_ar", "usual_qty", "days_since", "median_gap_days", "due_score")}
                          for p in predictions(self.store, ctx["user_id"], ctx["now"])]}

    def t_rides_get_quote(self, ctx, pickup, dropoff, product=None):
        if not self.rides:
            return {"error": "rides cannot be booked in this setup yet"}
        a, b = self.places.get(pickup), self.places.get(dropoff)
        if not a or not b:
            return {"error": f"unknown place; saved places: {list(self.places)}"}
        km = _km(a, b)
        quotes = [{"product": p, "price_aed": round(base + per_km * km, 2), "eta_min": 4 + i * 2}
                  for i, (p, (base, per_km)) in enumerate(RIDE_PRODUCTS.items()) if not product or p == product]
        amman = os.getenv("SANDBOX_WORLD", "dubai").lower() == "amman"  # the demo world is Amman: price rides in JOD
        for x in quotes:
            # Amman fares, not Dubai fares converted: a ~10 km Go across Amman is about 5 JOD, rounded to 0.05 like the app shows
            x["price"], x["currency"] = (round(x["price_aed"] * 0.102 * 20) / 20, "JOD") if amman else (x["price_aed"], "AED")
        quote_id = "rq_" + uuid.uuid4().hex[:8]
        self.store.state.setdefault("ride_quotes", {})[quote_id] = {"pickup": pickup, "dropoff": dropoff, "km": round(km, 1),
                                                                     "quotes": quotes}
        self.store.save()
        return {"quote_id": quote_id, "pickup": pickup, "dropoff": dropoff, "distance_km": round(km, 1), "quotes": quotes,
                "note": "for rides_request use checkout_args {quote_id, product}"}

    def t_request_confirmation(self, ctx, by, checkout_tool, checkout_args, total, summary, currency="AED"):
        uid = ctx["user_id"]
        by = self.store.users[uid]["name"] if by.lower() in ("user", "me", self.store.users[uid]["name"].lower()) else by
        if by not in g.allowed_confirmers(self.store, uid):
            return {"error": f"{by} cannot confirm; allowed: {g.allowed_confirmers(self.store, uid)}"}
        if checkout_tool not in SPENDING or (checkout_tool == "rides_request" and not self.rides):
            return {"error": f"checkout_tool must be one of {list(SPENDING)}"}
        problem = self._check_args(checkout_tool, checkout_args)
        if problem:
            return {"error": problem}
        real_total, real_currency, problem = self._real_price(uid, checkout_tool, checkout_args)
        if problem:
            return {"error": problem}
        if not (_positive(total) and _positive(real_total)) or abs(float(total) - real_total) > 0.5 \
                or (currency or "").upper() != real_currency:
            return {"error": f"the price is {real_total} {real_currency} according to Careem, not {total} {currency}; "
                             "tell the user the real price"}
        summary = f"{SPENDING[checkout_tool]}, {real_total} {real_currency}: {summary}"
        self.store.state["pending"][uid] = {"by": by, "ts": ctx["now"].isoformat(timespec="minutes"), "turn": ctx.get("turn"),
                                             "tool": checkout_tool, "args": checkout_args, "total": real_total,
                                             "currency": real_currency, "summary": summary}
        self.store.log(uid, "confirmation_requested", ctx["now"], by=by, tool=checkout_tool)
        return {"status": "waiting", "by": by, "summary": summary, "total": real_total, "currency": real_currency,
                "note": "tell the user it is waiting for confirmation; do not say it is ordered"
                if by != self.store.users[uid]["name"] else
                f"ask the user to say yes to confirm; {self.store.users[uid].get('confirm_by', 'the family')} can also "
                "approve it in their app, whoever is first"}

    def _real_price(self, uid, tool, args):
        """(total, currency, problem) from Careem's own answers, tied to this exact checkout: the ride quote, the
        Box quote for the same delivery, or the priced basket with this basket_id. Anything missing fails closed."""
        prices = self.store.state.get("careem_prices", {}).get(uid, {})
        if tool == "rides_request":
            q = self.store.state["ride_quotes"][args["quote_id"]]
            x = next(x for x in q["quotes"] if x["product"] == args["product"])
            return x.get("price", x["price_aed"]), x.get("currency", "AED"), None
        if tool == "box_create_order":
            box = prices.get("box")
            if not box or any(box.get(k) is None or str(box[k]) != str(args.get(k)) for k in BOX_BINDING):
                return None, None, "price this exact Box delivery with box_pre_checkout first"
            if dt.datetime.now() - dt.datetime.fromisoformat(box["ts"]) > QUOTE_MAX_AGE:
                return None, None, "the Box quote is too old; call box_pre_checkout again"
            if not _positive(box.get("max_price")) or not box.get("currency"):
                return None, None, "Careem gave no usable price for this Box delivery"
            return float(box["max_price"]), str(box["currency"]).upper(), None
        basket = prices.get("baskets", {}).get(str(args.get("basket_id")))
        if not basket:
            return None, None, "price this basket first (cart_get_basket_price), after the last cart change"
        if not _positive(args.get("total_price")) or abs(float(args["total_price"]) - basket["total"]) > 0.01:
            return None, None, f"total_price must be the basket's price from Careem: {basket['total']} {basket['currency']}"
        return basket["total"], basket["currency"], None

    def _check_args(self, tool, args):
        if not isinstance(args, dict):
            return "checkout_args must be an object"
        if tool == "rides_request":
            q = self.store.state.get("ride_quotes", {}).get(args.get("quote_id"))
            if not q:
                return "unknown quote_id: call rides_get_quote first"
            if args.get("product") not in [x["product"] for x in q["quotes"]]:
                return f"product must be one of {[x['product'] for x in q['quotes']]}"
            return None
        schema = self.mcp.tools()[tool]["inputSchema"]
        for k in [k for k in args if k not in schema.get("properties", {})]:
            args.pop(k)  # fields from the quote that the checkout does not take
        errors = list(Draft202012Validator(schema).iter_errors(args))
        return f"checkout_args do not fit {tool}: {errors[0].message}" if errors else None

    def t_place_order(self, ctx, confirmed_by):
        uid = ctx["user_id"]
        if confirmed_by.lower() in ("user", "me"):
            confirmed_by = self.store.users[uid]["name"]
        if confirmed_by != self.store.users[uid]["name"]:
            # family members approve only in their own app (Brain.family_decision), never through the LLM
            self.store.log(uid, "guardrail", ctx["now"], check="place_order", ok=False, reason="family approval must come from the family app")
            return {"error": f"BLOCKED by guardrail: {confirmed_by} must approve in their app; tell the user it is waiting for them"}
        pending = self.store.state["pending"].get(uid)
        if pending and pending.get("turn") == ctx.get("turn"):
            ok, reason = False, "the user must say yes in their next message"
        else:
            ok, reason = g.can_place_order(self.store, uid, confirmed_by, ctx.get("text"))
        self.store.log(uid, "guardrail", ctx["now"], check="place_order", ok=ok, reason=reason)
        if not ok:
            return {"error": "BLOCKED by guardrail: " + reason}
        return self.execute_pending(uid, confirmed_by, ctx["now"])

    def execute_pending(self, uid, confirmed_by, now):
        """Run the confirmed checkout once. It is never retried blindly: the pending call and its price are cleared."""
        p = self.store.state["pending"].pop(uid)
        prices = self.store.state.get("careem_prices", {}).get(uid, {})
        prices.pop("box", None) if p["tool"] == "box_create_order" else prices.pop("baskets", None)
        self.store.save()
        if p["tool"] != "rides_request" and not checkout_allowed():  # real account: never pay
            self.store.log(uid, "guardrail", now, check="checkout", ok=False, reason="checkout switched off")
            return {"status": "blocked", "service": SPENDING[p["tool"]], "result": {"error": CHECKOUT_OFF}}
        try:
            result = self._ride(p) if p["tool"] == "rides_request" else self.mcp.call(p["tool"], p["args"])
        except Exception as e:
            result = {"error": f"Careem service unavailable: {type(e).__name__}"}
        ok = isinstance(result, dict) and not result.get("error")
        self.store.state.setdefault("service_orders", []).append({
            "user_id": uid, "ts": now.isoformat(timespec="minutes"), "service": SPENDING[p["tool"]], "tool": p["tool"],
            "summary": p["summary"], "total": p["total"], "currency": p["currency"], "confirmed_by": confirmed_by,
            "ok": ok, "result": {k: result.get(k) for k in ("order_id", "orderId", "invoice_id", "ride_id", "error") if k in result}})
        self.store.log(uid, "order_placed" if ok else "order_failed", now, tool=p["tool"], by=confirmed_by)
        return {"status": "ordered" if ok else "failed", "service": SPENDING[p["tool"]], "result": _compact(result, 2000)}

    def _ride(self, p):
        q = self.store.state.get("ride_quotes", {}).get(p["args"]["quote_id"])
        x = next(x for x in q["quotes"] if x["product"] == p["args"]["product"])
        # the price and currency that were quoted and confirmed (JOD in the Amman world); reporting price_aed here made
        # the agent warn Faris that the price "changed" to ~49 dirhams after he agreed to 9.45 JOD
        return {"ride_id": "ride_" + uuid.uuid4().hex[:6], "status": "captain_assigned", "captain": "Ahmed K.",
                "eta_min": x.get("eta_min", 4), "product": p["args"]["product"], "from": q["pickup"], "to": q["dropoff"],
                "price": x.get("price", x["price_aed"]), "currency": x.get("currency", "AED")}

    def t_memory_list(self, ctx):
        return {"facts": self.memory.all(ctx["user_id"])}

    def t_memory_forget(self, ctx, memory_id):
        return {"deleted": self.memory.forget(ctx["user_id"], None if memory_id == "all" else memory_id)}

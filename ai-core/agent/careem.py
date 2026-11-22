"""Careem services through MCP (careem-mcp: groceries, food, cart, Box, user) plus a local rides stand-in.

The LLM sees Careem's real tool definitions, except the three that spend money. To pay, it proposes the exact
checkout call with request_confirmation; this code runs it only after the user's clear yes or the family's approval.
"""
import json
import math
import os
import uuid

from jsonschema import Draft202012Validator

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
        local = [
            ("rides_get_quote", "Price a Careem ride between two saved places (labels like Home, Work, Gym, Dubai Mall, Airport T3).",
             {"pickup": S, "dropoff": S, "product": {"type": "string", "enum": list(RIDE_PRODUCTS)}}, ["pickup", "dropoff"]),
            ("usual_basket", "The user's usual grocery items with days since each was last bought and whether it is running out.", {}, []),
            ("request_confirmation",
             "Before anything is ordered or booked: propose the exact checkout call and ask the user (by='user') or the family "
             "member who confirms. checkout_tool is one of cart_grocery_checkout, cart_checkout, box_create_order, rides_request; "
             "checkout_args are its exact arguments (for rides_request: the quote_id from rides_get_quote); total is the price.",
             {"by": S, "checkout_tool": {"type": "string", "enum": list(SPENDING)}, "checkout_args": {"type": "object"},
              "total": {"type": "number"}, "currency": S, "summary": S},
             ["by", "checkout_tool", "checkout_args", "total", "summary"]),
            ("place_order", "Run the confirmed checkout after the USER said yes to request_confirmation(by='user'). "
             "Family members approve in their own app, never here.", {"confirmed_by": S}, ["confirmed_by"]),
            ("memory_list", "Everything remembered about the user (answer 'what do you know about me?').", {}, []),
            ("memory_forget", "Delete one remembered fact by id, or everything when memory_id is 'all'.", {"memory_id": S}, ["memory_id"]),
        ]
        out += [{"type": "function", "function": {"name": n, "description": d,
                                                        "parameters": {"type": "object", "properties": p, "required": r}}}
                for n, d, p, r in local]
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
        if not isinstance(result, dict) or result.get("error"):
            return
        prices = self.store.state.setdefault("careem_prices", {}).setdefault(uid, {})
        if name == "box_pre_checkout" and isinstance(result.get("delivery_estimate"), dict):
            est = result["delivery_estimate"]
            prices["box"] = {"cct_id": result.get("cct_id", args.get("cct_id")), "max_price": est.get("max_price"),
                             "currency": est.get("currency_code"),
                             "pickup_location_id": result.get("pickup_location_id"),
                             "dropoff_location_id": result.get("dropoff_location_id")}
        currency = _find(result, ("currency_code", "currency"))
        if name.startswith(("cart_", "create_grocery")) and isinstance(currency, str):
            prices["cart_currency"] = currency
        self.store.save()

    # ---------- local tools ----------
    def t_usual_basket(self, ctx):
        return {"items": [{k: p[k] for k in ("name_en", "name_ar", "usual_qty", "days_since", "median_gap_days", "due_score")}
                          for p in predictions(self.store, ctx["user_id"], ctx["now"])]}

    def t_rides_get_quote(self, ctx, pickup, dropoff, product=None):
        a, b = self.places.get(pickup), self.places.get(dropoff)
        if not a or not b:
            return {"error": f"unknown place; saved places: {list(self.places)}"}
        km = _km(a, b)
        quotes = [{"product": p, "price_aed": round(base + per_km * km, 2), "eta_min": 4 + i * 2}
                  for i, (p, (base, per_km)) in enumerate(RIDE_PRODUCTS.items()) if not product or p == product]
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
        if checkout_tool not in SPENDING:
            return {"error": f"checkout_tool must be one of {list(SPENDING)}"}
        problem = self._check_args(checkout_tool, checkout_args)
        if problem:
            return {"error": problem}
        real_total, real_currency, problem = self._real_price(uid, checkout_tool, checkout_args)
        if problem:
            return {"error": problem}
        if abs(float(total) - real_total) > 0.5 or (currency or "").upper() != real_currency:
            return {"error": f"the price is {real_total} {real_currency} according to Careem, not {total} {currency}; "
                             "tell the user the real price"}
        summary = f"{SPENDING[checkout_tool]}, {real_total} {real_currency}: {summary}"
        self.store.state["pending"][uid] = {"by": by, "ts": ctx["now"].isoformat(timespec="minutes"), "turn": ctx.get("turn"),
                                             "tool": checkout_tool, "args": checkout_args, "total": real_total,
                                             "currency": real_currency, "summary": summary}
        self.store.log(uid, "confirmation_requested", ctx["now"], by=by, tool=checkout_tool)
        return {"status": "waiting", "by": by, "summary": summary, "total": real_total, "currency": real_currency,
                "note": "tell the user it is waiting for confirmation; do not say it is ordered"
                if by != self.store.users[uid]["name"] else "ask the user to say yes to confirm"}

    def _real_price(self, uid, tool, args):
        """(total, currency, problem) from Careem's own answers: the ride quote, the Box quote, or the total_price
        the cart checkout will charge (Careem rejects it if it no longer matches the basket)."""
        prices = self.store.state.get("careem_prices", {}).get(uid, {})
        if tool == "rides_request":
            q = self.store.state["ride_quotes"][args["quote_id"]]
            return next(x["price_aed"] for x in q["quotes"] if x["product"] == args["product"]), "AED", None
        if tool == "box_create_order":
            box = prices.get("box")
            same = box and all(str(box.get(k)) == str(args.get(k)) for k in ("cct_id", "pickup_location_id", "dropoff_location_id")
                               if box.get(k) is not None)
            if not same or box.get("max_price") is None:
                return None, None, "price this exact Box delivery with box_pre_checkout first"
            return float(box["max_price"]), str(box.get("currency") or "").upper(), None
        currency = prices.get("cart_currency")
        if not currency:
            return None, None, "price the cart first (cart_get_basket_price)"
        return float(args["total_price"]), currency.upper(), None

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
        """Run the confirmed checkout once. It is never retried blindly: the pending call is cleared either way."""
        p = self.store.state["pending"].pop(uid)
        self.store.save()
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
        price = next(x["price_aed"] for x in q["quotes"] if x["product"] == p["args"]["product"])
        return {"ride_id": "ride_" + uuid.uuid4().hex[:6], "status": "captain_assigned", "captain": "Ahmed K.",
                "eta_min": 5, "product": p["args"]["product"], "from": q["pickup"], "to": q["dropoff"], "price_aed": price}

    def t_memory_list(self, ctx):
        return {"facts": self.memory.all(ctx["user_id"])}

    def t_memory_forget(self, ctx, memory_id):
        return {"deleted": self.memory.forget(ctx["user_id"], None if memory_id == "all" else memory_id)}

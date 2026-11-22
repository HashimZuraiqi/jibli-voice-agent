"""Real Careem tools through the Careem MCP server (CAREEM_PROVIDER=mcp). The mocks in tools.py stay the default/backup.

How it works:
- On start we ask the server for its tool list and hand those tools to the LLM as they are (names, descriptions and
  argument schemas come from Careem), so we don't hard-code arguments we haven't seen.
- `cart_grocery_checkout` is NEVER given to the LLM. Only our confirm gate calls it: place_order (the user's own yes
  in a later message) or family_checkout (the family member's approve button). It is called once and never retried.
- Its arguments are filled from values seen in earlier calls (cart id, lat/lng, address id, ...), so the LLM can't
  invent them.

- lat/lng are filled in on every call whose schema asks for them: from user_info (saved address) when seen,
  else CAREEM_LAT / CAREEM_LNG.
- A basket whose total can't be read is never checked out on the user's own yes: the family member approves it.

Settings (.env): CAREEM_PROVIDER=mcp, CAREEM_MCP_URL, CAREEM_MCP_TOKEN (sent as Bearer), CAREEM_MCP_TRANSPORT=http|sse.
Uses the MCP Python SDK 2.x (mcp.Client).
- Local sandbox (fake Dubai data, never orders): CAREEM_MCP_URL=http://127.0.0.1:8787/mcp, no token.
- Production (REAL account, REAL orders and money): CAREEM_MCP_URL=https://mcp.careemapis.com/mcp, token from
  scripts/careem_login.py (OAuth PKCE with the hackathon client id).
"""
import asyncio
import hashlib
import json
import os
import re

from .personalization import guardrails as g

CHECKOUT = "cart_grocery_checkout"
PRICE = "cart_get_basket_price"
TOTAL_KEYS = ("total", "totalprice", "baskettotal", "grandtotal", "amount")
# Only these Careem tools reach the LLM (grocery journey + read-only helpers). Everything else, including every
# tool that spends money or books something (cart_checkout, cart_add_item, cart_reorder, box_create_order,
# create_ride, cancel_ride, save_new_address, apply_promotion_code, ...), is never offered.
# create_grocery_cart_with_quantities is the one mutating tool allowed: it only builds a basket, nothing is bought.
DEFAULT_ALLOWED = ("user_info,get_activities,track_activity,is_grocery_area_serviceable,search_groceries_items,"
                   "search_groceries_get_top_user_items,search_groceries_get_all_deals,"
                   "create_grocery_cart_with_quantities,cart_get_quik_basket,cart_get_basket_price,cart_get_checkout_promos")
# checkout argument -> keys that hold its value (normalized: lowercase, no _ or -)
# taken ONLY from the confirmed basket (cart_get_basket_price), never from an older answer:
ALIASES = {"totalprice": ("totalprice", "total", "baskettotal", "grandtotal"),
           "paymentid": ("paymentid", "paymentmethodid"),        # the card the basket was priced with
           "paymenttype": ("paymenttype", "paymentmethodtype")}
# taken from any earlier answer or argument (user_info gives city_timezone / city_currency):
SEEN_ALIASES = {"timezone": ("timezone", "citytimezone"), "currency": ("currency", "citycurrency")}
# the spend cap is in JOD; the sandbox prices in AED (fake Dubai data), production in the user's currency
TO_JOD = {"JOD": 1.0, "JD": 1.0, "AED": 0.193, "SAR": 0.189, "USD": 0.709}
LAT_KEYS, LNG_KEYS = ("lat", "latitude"), ("lng", "lon", "long", "longitude")


def is_production(url=None):
    """True when talking to Careem's real server (real account, real orders)."""
    url = os.getenv("CAREEM_MCP_URL", "") if url is None else url
    return isinstance(url, str) and "careemapis.com" in url


def checkout_allowed():
    """CAREEM_ALLOW_CHECKOUT=true|false. Unset: off on the real Careem server, on for the local sandbox."""
    value = os.getenv("CAREEM_ALLOW_CHECKOUT", "").strip().lower()
    return value == "true" if value else not is_production()


CHECKOUT_OFF = ("checkout is switched off (CAREEM_ALLOW_CHECKOUT): the real cart and price are ready, nothing was "
                "paid; the order can be finished in the Careem app")


class MCPConnector:
    """Minimal sync wrapper around the MCP Python SDK: one short connection per call (simple and robust for a demo)."""

    def __init__(self, url=None, token=None, transport=None):
        """url: the server URL (default CAREEM_MCP_URL), or an in-process MCP server object in tests."""
        self.url = url or os.getenv("CAREEM_MCP_URL", "")
        if not self.url:
            raise RuntimeError("CAREEM_MCP_URL is not set")
        self.token = token
        self.transport = (transport or os.getenv("CAREEM_MCP_TRANSPORT", "http")).lower()

    @property
    def headers(self):
        """Re-read the token each call, so scripts/careem_login.py --refresh works without a restart."""
        token = self.token
        if token is None:
            from pathlib import Path
            env = Path(__file__).resolve().parents[1] / ".env"
            if env.exists():
                from dotenv import dotenv_values
                token = dotenv_values(env).get("CAREEM_MCP_TOKEN") or os.getenv("CAREEM_MCP_TOKEN", "")
            else:
                token = os.getenv("CAREEM_MCP_TOKEN", "")
        return {"Authorization": f"Bearer {token}"} if token else {}

    def transport_for_url(self):
        if not isinstance(self.url, str):  # in-process server (tests)
            return self.url
        if self.transport == "sse":
            from mcp.client.sse import sse_client
            return sse_client(self.url, headers=self.headers)
        from mcp.client.streamable_http import create_mcp_http_client, streamable_http_client
        return streamable_http_client(self.url, http_client=create_mcp_http_client(headers=self.headers))

    async def _session(self, fn):
        from mcp import Client
        async with Client(self.transport_for_url()) as c:
            return await fn(c)

        if self.transport == "sse":
            from mcp.client.sse import sse_client
            async with sse_client(self.url, headers=self.headers) as streams:
                return await run(streams)
        try:  # mcp >= 2: headers go on an httpx2 client we pass in (and close ourselves)
            from mcp.client.streamable_http import streamable_http_client
            from mcp.shared._httpx_utils import create_mcp_http_client
        except ImportError:  # mcp 1.x
            from mcp.client.streamable_http import streamablehttp_client
            async with streamablehttp_client(self.url, headers=self.headers) as streams:
                return await run(streams)
        async with create_mcp_http_client(headers=self.headers) as http:
            async with streamable_http_client(self.url, http_client=http) as streams:
                return await run(streams)

    def list_tools(self):
        async def go(c):
            return [{"name": t.name, "description": t.description or "", "inputSchema": t.input_schema or {"type": "object"}}
                    for t in (await c.list_tools()).tools]
        return asyncio.run(self._session(go))

    def call(self, name, args):
        async def go(c):
            r = await c.call_tool(name, args)
            if getattr(r, "structured_content", None):
                out = r.structured_content
            else:
                text = "\n".join(getattr(b, "text", "") for b in (r.content or []) if getattr(b, "type", "") == "text")
                try:
                    out = json.loads(text)
                except json.JSONDecodeError:
                    out = {"text": text}
            if getattr(r, "is_error", False):
                return {"error": out}
            return out
        return asyncio.run(self._session(go))


def is_cart_change(name):
    """Tools that change the basket. Reads (cart_get_basket_price, cart_get_quik_basket, cart_get_checkout_promos, ...)
    don't, so re-checking the cart before checkout must not cancel the confirmation."""
    return ("cart" in name and not name.startswith("cart_get_")) or name == "create_grocery_cart_with_quantities"


def flatten(obj, out=None):
    """Every scalar leaf by its key name (latest wins), e.g. {'cart': {'id': 7}} -> {'cart_id': 7, 'id': 7}."""
    out = {} if out is None else out

    def walk(o, parent=""):
        if isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, (dict, list)):
                    walk(v, k)
                else:
                    out[k] = v
                    if parent:
                        out[f"{parent}_{k}"] = v
        elif isinstance(o, list) and o and isinstance(o[0], dict) and len(o) == 1:
            walk(o[0], parent)
    walk(obj)
    return out


def norm_key(k):
    return re.sub(r"[^a-z0-9]", "", k.lower())


class CareemMCPTools:
    def __init__(self, store, memory, local_tools, connector=None):
        self.store, self.memory, self.local = store, memory, local_tools
        self.mcp = connector or MCPConnector()
        allowed = {n.strip() for n in os.getenv("CAREEM_ALLOWED_TOOLS", DEFAULT_ALLOWED).split(",") if n.strip()}
        everything = {t["name"]: t for t in self.mcp.list_tools()}
        if CHECKOUT not in everything:
            raise RuntimeError(f"Careem MCP has no {CHECKOUT}; tools: {sorted(everything)}")
        self.checkout_tool = everything[CHECKOUT]
        self.remote = {n: t for n, t in everything.items() if n in allowed and n != CHECKOUT}

    # -- per-user MCP state (kept in the store so the web panel and restarts see it) --
    def st(self, uid):
        return self.store.state.setdefault("mcp", {}).setdefault(uid, {"seen": {}, "basket": None, "done": {}})

    def with_location(self, uid, schema, args):
        """Fill lat/lng into args when the schema has them and they are missing: saved address first, else env."""
        props = (schema or {}).get("properties") or {}
        seen = {norm_key(k): v for k, v in self.st(uid)["seen"].items()}
        defaults = (float(os.getenv("CAREEM_LAT", "31.9539")), float(os.getenv("CAREEM_LNG", "35.9106")))  # Amman
        args = dict(args)
        for keys, default in zip((LAT_KEYS, LNG_KEYS), defaults):
            prop = next((p for p in props if norm_key(p) in keys), None)
            if prop and args.get(prop) in (None, ""):
                args[prop] = next((seen[k] for k in keys if seen.get(k) not in (None, "")), default)
        return args

    def schemas(self):
        out = [{"type": "function", "function": {"name": n, "description": t["description"][:1000],
                                                 "parameters": t["inputSchema"] or {"type": "object", "properties": {}}}}
               for n, t in self.remote.items()]
        S = {"type": "string"}
        own = [("request_confirmation", "Ask for confirmation before ordering. Call cart_get_basket_price first. "
                "by='user' to ask the user, or the family member's name.", {"by": S}, ["by"]),
               ("place_order", "Place the order after the USER said yes to request_confirmation(by='user'). "
                "Family members approve in their own app, never here.", {"confirmed_by": S}, ["confirmed_by"])]
        own += [s for s in self.local.specs() if s[0] in ("memory_list", "memory_forget")]
        return out + [{"type": "function", "function": {"name": n, "description": d,
                                                        "parameters": {"type": "object", "properties": p, "required": r}}}
                      for n, d, p, r in own]

    def run(self, name, args, ctx):
        uid = ctx["user_id"]
        if name == CHECKOUT:
            self.store.log(uid, "guardrail", ctx["now"], check="checkout", ok=False, reason="the LLM cannot check out")
            return {"error": "BLOCKED: checkout only happens through request_confirmation and a human yes"}
        if name in ("memory_list", "memory_forget"):
            return self.local.run(name, args, ctx)
        if name == "request_confirmation":
            return self.request_confirmation(ctx, **args)
        if name == "place_order":
            return self.place_order(ctx, **args)
        if name not in self.remote:
            return {"error": f"tool {name} is not available to this agent"}
        args = self.with_location(uid, self.remote[name]["inputSchema"], args)
        try:
            result = self.mcp.call(name, args)
        except Exception as e:
            return {"error": f"Careem MCP call failed: {type(e).__name__}: {str(e)[:200]}"}
        st = self.st(uid)
        # what Careem answered beats what the LLM typed (it once sent city_id=0 over user_info's real city_id=1)
        flatten(args, st.setdefault("args", {}))
        if isinstance(result, dict) and "error" not in result:
            flatten(result, st["seen"])
        if name == PRICE and "error" not in result:
            st["basket"] = result
        elif is_cart_change(name):  # any cart change needs a new price and a new confirmation
            st["basket"] = None
            self.store.state["pending"].pop(uid, None)
        self.store.save()
        return result

    # -- confirm gate --
    @staticmethod
    def fingerprint(basket):
        return hashlib.sha1(json.dumps(basket, sort_keys=True, default=str).encode()).hexdigest()[:12]

    @staticmethod
    def total(basket):
        for k, v in flatten(basket).items():
            if norm_key(k) in TOTAL_KEYS:
                try:
                    return float(str(v).replace("JOD", "").replace("JD", "").strip())
                except ValueError:
                    pass
        return None

    @staticmethod
    def currency(basket):
        for k, v in flatten(basket).items():
            if norm_key(k) in ("currency", "currencycode") and isinstance(v, str):
                return v.upper()
        return "JOD"

    def request_confirmation(self, ctx, by):
        uid = ctx["user_id"]
        basket = self.st(uid)["basket"]
        if not basket:
            return {"error": "no priced cart yet: create the cart, then call cart_get_basket_price"}
        name = self.store.users[uid]["name"]
        by = name if by.lower() in ("user", "me", name.lower()) else by
        if by not in g.allowed_confirmers(self.store, uid):
            return {"error": f"{by} cannot confirm; allowed: {g.allowed_confirmers(self.store, uid)}"}
        old = self.store.state["pending"].get(uid)
        if old and old["by"] == by and old["basket"] == self.fingerprint(basket):
            # asked again for the same basket: keep the original turn, so the yes that answered it still counts
            return {"status": "waiting", "by": by, "basket": basket,
                    "note": "already asked for this exact basket: if the user has just said yes, call place_order now"
                    if by == name else "still waiting for the family member's approval; do not place the order"}
        self.store.state["pending"][uid] = {"by": by, "ts": ctx["now"].isoformat(timespec="minutes"), "turn": ctx.get("turn"),
                                            "basket": self.fingerprint(basket), "cart": basket}
        self.store.log(uid, "confirmation_requested", ctx["now"], by=by)
        self.store.save()
        return {"status": "waiting", "by": by, "basket": basket,
                "note": "ask the user to say yes to confirm" if by == name
                else "tell the user it is waiting for confirmation; do not place the order yet"}

    def check(self, uid, by, user_text=None, turn=None):
        st, pending = self.st(uid), self.store.state["pending"].get(uid)
        if not pending:
            return False, "ask for confirmation first (request_confirmation), then wait for the answer"
        if pending["by"] != by:
            return False, f"confirmation was requested from {pending['by']}, not {by}"
        if not st["basket"] or self.fingerprint(st["basket"]) != pending["basket"]:
            return False, "the cart changed after confirmation was requested; ask again"
        total, cur = self.total(st["basket"]), self.currency(st["basket"])
        if total is not None and total * TO_JOD.get(cur, 1.0) > g.SPEND_CAP_JOD:
            return False, f"total {total} {cur} is over the {g.SPEND_CAP_JOD} JOD cap"
        if total is None and by == self.store.users[uid]["name"]:
            return False, "the basket total is unknown; the family member must approve it in their app"
        if by == self.store.users[uid]["name"]:
            if turn is not None and pending.get("turn") == turn:
                return False, "the user must say yes in their next message"
            if not g.says_yes(user_text):
                return False, "the user has not clearly said yes in this message"
        return True, "ok"

    def place_order(self, ctx, confirmed_by):
        uid, name = ctx["user_id"], self.store.users[ctx["user_id"]]["name"]
        if confirmed_by.lower() in ("user", "me"):
            confirmed_by = name
        if confirmed_by != name:
            self.store.log(uid, "guardrail", ctx["now"], check="place_order", ok=False, reason="family approval must come from the family app")
            return {"error": f"BLOCKED by guardrail: {confirmed_by} must approve in their app; tell the user it is waiting for them"}
        ok, reason = self.check(uid, name, ctx.get("text"), ctx.get("turn"))
        self.store.log(uid, "guardrail", ctx["now"], check="place_order", ok=ok, reason=reason)
        if not ok:
            return {"error": "BLOCKED by guardrail: " + reason}
        return self.checkout(uid, name, ctx["now"])

    def family_checkout(self, uid, by, now):
        """The family member pressed Approve in their app (Brain.family_decision)."""
        ok, reason = self.check(uid, by)
        self.store.log(uid, "guardrail", now, check="place_order", ok=ok, reason=reason)
        if not ok:
            return {"status": "blocked", "reason": reason}
        return self.checkout(uid, by, now)

    def checkout_args(self, uid):
        schema = self.checkout_tool["inputSchema"] or {}
        filled = self.with_location(uid, schema, {})  # lat/lng fallback: saved address or CAREEM_LAT / CAREEM_LNG
        st, required = self.st(uid), set(schema.get("required", []))
        answers = {norm_key(k): v for k, v in st["seen"].items()}
        typed = {norm_key(k): v for k, v in st.get("args", {}).items()}
        basket = {norm_key(k): v for k, v in flatten(st["basket"] or {}).items()}
        args, missing = {}, []
        for prop in (schema.get("properties") or {}):
            key = norm_key(prop)
            # Careem's answers win; what the LLM typed only fills REQUIRED args (lat/lng). Optional ones Careem
            # resolves itself, so a guess (the LLM once sent city_id=0) must never reach checkout.
            seen = {**typed, **answers} if prop in required else answers
            # the price must come from the basket that was confirmed, never from an older answer
            v = next((basket[a] for a in ALIASES.get(key, ()) if a in basket), None)
            if v is None and key not in ALIASES:
                v = next((seen[a] for a in SEEN_ALIASES.get(key, (key,)) if a in seen), None)
            if v is None:
                v = filled.get(prop)  # lat/lng: saved address or CAREEM_LAT / CAREEM_LNG
            if v is not None:
                args[prop] = v
            elif prop in required:
                missing.append(prop)
        return args, missing

    def checkout(self, uid, by, now):
        st = self.st(uid)
        fp = self.fingerprint(st["basket"])
        if fp in st["done"]:  # double tap / repeated yes: never order the same basket twice
            self.store.state["pending"].pop(uid, None)  # the request is answered: don't leave it waiting
            self.store.save()
            return {"status": "ordered", "order": st["done"][fp], "note": "already ordered"}
        if st.get("failed") == fp:  # it may have gone through on Careem's side: a human checks, then builds a new cart
            return {"status": "error", "error": "checkout already failed for this cart; check the Careem app, then make a new cart"}
        args, missing = self.checkout_args(uid)
        if missing:
            return {"status": "blocked", "error": f"checkout needs {missing}, not seen in earlier Careem calls"}
        if not checkout_allowed():  # real account: build the cart, never pay
            self.store.state["pending"].pop(uid, None)
            self.store.log(uid, "guardrail", now, check="checkout", ok=False, reason="checkout switched off")
            return {"status": "blocked", "error": CHECKOUT_OFF}
        try:
            result = self.mcp.call(CHECKOUT, args)
        except Exception as e:  # never retry checkout blindly: it may have gone through
            st["failed"] = fp
            self.store.save()
            self.store.log(uid, "careem_checkout_failed", now, by=by, error=str(e)[:200])
            return {"status": "error", "error": "checkout failed and was NOT retried; check the Careem app before trying again"}
        if isinstance(result, dict) and "error" in result:
            st["failed"] = fp
            self.store.log(uid, "careem_checkout_failed", now, by=by, error=str(result["error"])[:200])
            return {"status": "error", "error": result["error"]}
        order = {"confirmed_by": by, "ts": now.isoformat(timespec="minutes"), "careem": result,
                 "total": self.total(st["basket"])}
        st["done"][fp] = order
        st["basket"] = None
        self.store.state["pending"].pop(uid, None)
        self.store.log(uid, "careem_order", now, by=by, total=order["total"])
        return {"status": "ordered", "order": order}


def make_tools(store, memory, places=None):
    """CAREEM_PROVIDER=mock (default, local data), mcp (real Careem, groceries) or mcp-all (groceries, food, Box and
    rides through agent/careem.py). If MCP can't start, say so and use the mocks."""
    from .tools import Tools
    local = Tools(store, memory)
    provider = os.getenv("CAREEM_PROVIDER", "mock").lower()
    if provider not in ("mcp", "mcp-all"):
        return local
    try:
        if provider == "mcp-all":
            from .careem import CareemTools
            from .personalization import services
            # the sandbox's saved places belong to its test account; on the real server user_info gives the user's own
            return CareemTools(store, memory, {} if is_production() else (places or services.load()["places"]))
        return CareemMCPTools(store, memory, local)
    except Exception as e:
        print(f"[careem] MCP unavailable, using mock tools: {type(e).__name__}: {e}")
        return local

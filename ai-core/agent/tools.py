"""Mocked Careem Quik tools the LLM can call. Every order-changing action goes through the guardrails."""
import re

from .personalization import guardrails as g
from .personalization.repurchase import predictions


def _norm(s):
    return re.sub(r"[ً-ْ]", "", s.lower()).replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ة", "ه")


class Tools:
    def __init__(self, store, memory):
        self.store, self.memory = store, memory

    def specs(self):
        S = {"type": "string"}
        return [
            ("search_catalog", "Find products by name in Arabic or English (e.g. 'خبز', 'rice').", {"query": S}, ["query"]),
            ("usual_basket", "The user's usual items with how many days since each was last bought and whether it is running out.", {}, []),
            ("add_to_cart", "Add an item (item_id from search_catalog or usual_basket) to the cart.",
             {"item_id": S, "qty": {"type": "integer"}}, ["item_id"]),
            ("remove_from_cart", "Remove an item from the cart.", {"item_id": S}, ["item_id"]),
            ("view_cart", "Show the cart and its total in JOD.", {}, []),
            ("request_confirmation", "Ask for confirmation before ordering: by='user' to ask the user, or the family member's name.",
             {"by": S}, ["by"]),
            ("place_order", "Place the order after the USER said yes to request_confirmation(by='user'). Family members approve in their own app, never here.",
             {"confirmed_by": S}, ["confirmed_by"]),
            ("memory_list", "Everything remembered about the user (answer 'what do you know about me?').", {}, []),
            ("memory_forget", "Delete one remembered fact by id, or everything when memory_id is 'all'.", {"memory_id": S}, ["memory_id"]),
        ]

    def schemas(self):
        return [{"type": "function", "function": {"name": n, "description": d,
                                                  "parameters": {"type": "object", "properties": p, "required": r}}}
                for n, d, p, r in self.specs()]

    def run(self, name, args, ctx):
        """ctx: user_id, now, text (the user's current message)."""
        fn = getattr(self, "t_" + name, None)
        if fn is None:
            return {"error": f"unknown tool {name}"}
        try:
            return fn(ctx, **args)
        except TypeError as e:
            return {"error": f"bad arguments: {e}"}

    # -- tools --
    def t_search_catalog(self, ctx, query):
        q = _norm(query)
        words = [w for w in q.split() if len(w) > 1]
        hits = [c for c in self.store.catalog.values()
                if any(w in _norm(c["name_en"] + " " + c["name_ar"] + " " + c["item_id"].replace("_", " ")) for w in words)]
        return {"results": [{"item_id": c["item_id"], "name_en": c["name_en"], "name_ar": c["name_ar"],
                             "price_jod": c["price_jod"]} for c in hits[:8]] or "no matching products"}

    def t_usual_basket(self, ctx):
        return {"items": [{k: p[k] for k in ("item_id", "name_en", "name_ar", "usual_qty", "days_since", "median_gap_days", "due_score")}
                          for p in predictions(self.store, ctx["user_id"], ctx["now"])]}

    def t_add_to_cart(self, ctx, item_id, qty=1):
        if item_id not in self.store.catalog:
            return {"error": f"unknown item_id {item_id}; use search_catalog"}
        if not 1 <= int(qty) <= 20:
            return {"error": "qty must be 1-20"}
        cart = self.store.cart(ctx["user_id"])
        cart[item_id] = cart.get(item_id, 0) + int(qty)
        self.store.state["pending"].pop(ctx["user_id"], None)  # a changed cart needs a new confirmation
        self.store.save()
        return self.store.cart_view(ctx["user_id"])

    def t_remove_from_cart(self, ctx, item_id):
        self.store.cart(ctx["user_id"]).pop(item_id, None)
        self.store.state["pending"].pop(ctx["user_id"], None)  # a changed cart needs a new confirmation
        self.store.save()
        return self.store.cart_view(ctx["user_id"])

    def t_view_cart(self, ctx):
        return self.store.cart_view(ctx["user_id"])

    def t_request_confirmation(self, ctx, by):
        uid = ctx["user_id"]
        if not self.store.cart(uid):
            return {"error": "the cart is empty"}
        by = self.store.users[uid]["name"] if by.lower() in ("user", "me", self.store.users[uid]["name"].lower()) else by
        if by not in g.allowed_confirmers(self.store, uid):
            return {"error": f"{by} cannot confirm; allowed: {g.allowed_confirmers(self.store, uid)}"}
        self.store.state["pending"][uid] = {"by": by, "ts": ctx["now"].isoformat(timespec="minutes"),
                                             "turn": ctx.get("turn"), "cart": self.store.cart_view(uid)}
        self.store.log(uid, "confirmation_requested", ctx["now"], by=by)
        return {"status": "waiting", "by": by, "cart": self.store.cart_view(uid),
                "note": "tell the user it is waiting for confirmation; do not place the order yet" if by != self.store.users[uid]["name"]
                else f"ask the user to say yes to confirm; {self.store.users[uid].get('confirm_by', 'the family')} can also "
                     "approve it in their app, whoever is first"}

    def t_place_order(self, ctx, confirmed_by):
        uid = ctx["user_id"]
        if confirmed_by.lower() in ("user", "me"):
            confirmed_by = self.store.users[uid]["name"]
        if confirmed_by != self.store.users[uid]["name"]:
            # family members approve only in their own app (Brain.family_decision), never through the LLM
            self.store.log(uid, "guardrail", ctx["now"], check="place_order", ok=False, reason="family approval must come from the family app")
            return {"error": f"BLOCKED by guardrail: {confirmed_by} must approve in their app; tell the user it is waiting for them"}
        pending = self.store.state["pending"].get(uid)
        # the user's own yes must come in a later message than the confirmation request
        if pending and confirmed_by == self.store.users[uid]["name"] and pending.get("turn") == ctx.get("turn"):
            ok, reason = False, "the user must say yes in their next message"
        else:
            ok, reason = g.can_place_order(self.store, uid, confirmed_by, ctx.get("text"))
        self.store.log(uid, "guardrail", ctx["now"], check="place_order", ok=ok, reason=reason)
        if not ok:
            return {"error": "BLOCKED by guardrail: " + reason}
        return {"status": "ordered", "order": self.store.place_order(uid, confirmed_by, ctx["now"])}

    def t_memory_list(self, ctx):
        return {"facts": self.memory.all(ctx["user_id"])}

    def t_memory_forget(self, ctx, memory_id):
        n = self.memory.forget(ctx["user_id"], None if memory_id == "all" else memory_id)
        return {"deleted": n}

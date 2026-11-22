"""The brain: 7 steps per user message (hear, remember, advise, think, act, confirm, learn)."""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .personalization import guardrails as g

PROMPTS = Path(__file__).resolve().parent / "prompts"
MAX_TOOL_ROUNDS = 12  # the real Careem chain (user_info, searches, cart, price, confirm, order) needs ~9-10
# every LLM round is a full Bedrock call, so fewer rounds = a faster answer
SPEED_RULE = ("\n\nSpeed: the user is waiting on a voice call. Call tools that don't depend on each other in the same turn "
              "(for example all product searches at once), don't call a tool whose answer you already have, and keep the "
              "spoken reply to one or two short sentences.")
BACKGROUND = ThreadPoolExecutor(max_workers=2)  # memory writes happen after the reply is sent


def ms(t0):
    return int((time.monotonic() - t0) * 1000)


def sandbox_note():
    """Careem's local sandbox answers every cart with the same fixed test basket, so on stage the agent would keep
    arguing that it doesn't match what was asked. Only on the sandbox: read the priced basket back as it is."""
    url = os.getenv("CAREEM_MCP_URL", "")
    if os.getenv("CAREEM_PROVIDER", "mock").lower() != "mcp" or not any(h in url for h in ("127.0.0.1", "localhost")):
        return ""
    if os.getenv("SANDBOX_WORLD", "dubai").lower() == "amman":
        return ""  # Amman mode: the sandbox builds the cart she asked for, so differences are real again
    return ("\n\nTest mode: this is Careem's MCP sandbox, which answers with a fixed test basket. After "
            "cart_get_basket_price, read back exactly what the priced basket contains (items, quantities, total, address) "
            "in one short sentence and ask for a yes. Do not point out differences from what the user asked for and do "
            "not ask them to choose between items; just read the basket and ask to confirm.")


# how to confirm depends on the Careem path: careem.py (mcp-all) proposes the exact checkout; careem_mcp.py (mcp)
# and the mocks only take who confirms, and the checkout is built from the priced basket by the gate
CONFIRM_ALL = ("- Nothing is ordered or booked until it is confirmed: call request_confirmation with the exact checkout_tool, "
               "checkout_args, total and a one-line summary; then stop and wait. Ask the user herself (by='user') by default: then "
               "she can say yes, or the family member who usually confirms can approve in their app, whoever is first. Ask only "
               "the family member when the user asks for that or a tool says the family must approve. Only call place_order when the user has just said yes. Never retry a failed checkout on your own; tell "
               "the user what went wrong.")
CONFIRM_GROCERY = ("- Nothing is ordered until it is confirmed: get the basket price first, then call request_confirmation and stop "
                   "and wait. Ask the user herself (by='user') by default: then she can say yes, or the family member who "
                   "usually confirms can approve in their app, whoever is first (say this in a few words). Ask only the family "
                   "member (by=<their name>) when the user asks for that or a tool says the family must approve. Only call "
                   "place_order when the user has just said yes; a family member approves in their own app. Never retry a "
                   "failed checkout on your own.")


def prompt(file, **kw):
    text = (PROMPTS / f"{file}.txt").read_text(encoding="utf-8")
    for k, v in kw.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def short(items):
    return ", ".join(f"{p['name_en']} / {p['name_ar']} (usual qty {p.get('usual_qty', 1)}, item_id {p['item_id']})" for p in items) or "nothing"


def ride_text(r):
    return f"usually {r['from']} -> {r['to']} by {r['product']} at this time ({r['times']} times)" if r else "none"


def box_text(b):
    if not b:
        return "none"
    due = "due again now" if b["due"] else f"last {b['days_since']} days ago"
    return f"usually {b['from']} -> {b['to']} by {b['vehicle']} ({b['category']}), every ~{b['median_gap_days']} days, {due}"


class Brain:
    def __init__(self, store, memory, layer, tools, llm):
        self.store, self.memory, self.layer, self.tools, self.llm = store, memory, layer, tools, llm
        self.history = {}  # short-term memory: this session's messages per user
        self.turn = 0

    def family_text(self, u):
        return "; ".join(f"{f['name']} ({f['relation']}{', pays' if f.get('pays') else ''}"
                         f"{', confirms orders' if f.get('can_confirm') else ''})" for f in u["family"])

    def system(self, user_id, now, memory_facts, advice):
        u = self.store.users[user_id]
        offer = (f"{advice['offer']['discount_pct']}% off this order (max {advice['offer']['max_jod']} JOD)"
                 if advice["offer"] else "none")
        return prompt("system", name=u["name"], name_ar=u["name_ar"], age=u["age"], city=u["city"],
                      now=now.strftime("%A %Y-%m-%d %H:%M"), family=self.family_text(u),
                      memory="\n".join("- " + m["fact"] for m in memory_facts) or "- nothing yet",
                      running_out=short(advice["running_out"]), cold_start=advice["cold_start"],
                      suggestions=("similar users usually buy: " + short(advice["suggestions_for_new_user"]))
                      if advice["cold_start"] else "",
                      style=advice["style"], style_hint=advice["style_hint"], offer=offer,
                      orders=self.orders_text(user_id),
                      confirm_rules=CONFIRM_ALL if hasattr(self.tools, "execute_pending") else CONFIRM_GROCERY, ride=ride_text(advice.get("usual_ride")),
                      box=box_text(advice.get("usual_box")), places=self.places_text()) + sandbox_note() + SPEED_RULE

    def places_text(self):
        places = getattr(self.tools, "places", None) or {}
        return "; ".join(f"{k} = {v['location_id']} ({v['latitude']}, {v['longitude']})" for k, v in places.items()) or "use user_info"

    def orders_text(self, user_id):
        lines = []
        pending = self.store.state["pending"].get(user_id)
        if pending and pending.get("tool"):
            lines.append(f"- waiting for {pending['by']} to approve: {pending['summary']} ({pending['total']} {pending['currency']})")
        elif pending and "total_jod" in (pending.get("cart") or {}):  # mock cart
            lines.append(f"- waiting for {pending['by']} to approve: {pending['cart']['total_jod']} JOD")
        elif pending:  # Careem MCP grocery basket (CAREEM_PROVIDER=mcp): Careem's own total and currency
            from .careem_mcp import CareemMCPTools as M
            cart = pending.get("cart") or {}
            lines.append(f"- waiting for {pending['by']} to approve: Quik groceries basket ({M.total(cart)} {M.currency(cart)})")
        # Careem MCP grocery orders (else the agent never hears that the family already approved and asks again)
        for o in list((self.store.state.get("mcp", {}).get(user_id) or {}).get("done", {}).values())[-3:][::-1]:
            cur = (o.get("careem") or {}).get("currency")
            lines.append(f"- groceries placed {o['ts'].replace('T', ' ')}, approved by {o['confirmed_by']}: "
                         f"Quik basket ({o.get('total')}{' ' + cur if cur else ''})")
        for o in [o for o in self.store.state.get("service_orders", []) if o["user_id"] == user_id][-3:][::-1]:
            lines.append(f"- {o['service']} {'placed' if o['ok'] else 'FAILED'} {o['ts'].replace('T', ' ')}, approved by "
                         f"{o['confirmed_by']}: {o['summary']} ({o['total']} {o['currency']})")
        for o in self.store.orders(user_id)[-2:][::-1]:
            names = ", ".join(f"{x['qty']}x {self.store.catalog[x['item_id']]['name_en']}" for x in o["items"])
            lines.append(f"- placed {o['ts'].replace('T', ' ')}, approved by {o['confirmed_by']}: {names} ({o['total']} JOD)")
        return "\n".join(lines) or "- none"

    def handle(self, user_id, text, now):
        self.turn += 1
        start = time.monotonic()
        steps = [{"step": "1 hear", "text": text}]
        self.memory.seed(user_id)

        t0 = time.monotonic()
        recall = BACKGROUND.submit(self.memory.recall, user_id, text)  # AgentCore search runs while the layer advises
        advice = self.layer.advise(user_id, now)
        advise_ms = ms(t0)
        facts = recall.result()
        steps.append({"step": "2 remember", "facts": [f["fact"] for f in facts], "ms": ms(t0)})
        open_reminder = [e for e in self.store.events(user_id, "reminder") if "reply" not in e]
        note = ""
        if open_reminder:  # the user's answer to our reminder is the bandit's reward
            reply = "no" if g.says_no(text) else "yes" if g.says_yes(text) else None
            if reply:
                self.layer.feedback(user_id, reply, now)
                steps.append({"step": "7 learn (reward)", "reminder_style": open_reminder[-1]["style"], "reply": reply})
                if reply == "yes":
                    note = ("\nThe user just said yes to your reminder. Prepare what it offered (" + self.reminder_items(advice)
                            + "): build the cart or quote with the tools, get its price, then request_confirmation from the "
                            "family member who usually confirms.")
        steps.append({"step": "3 advise", "running_out": [p["item_id"] for p in advice["running_out"]],
                      "style": advice["style"], "offer": advice["offer"], "offer_decision": advice["offer_decision"],
                      "ms": advise_ms})

        msgs = self.history.setdefault(user_id, [])
        msgs.append({"role": "user", "content": text})
        convo = [{"role": "system", "content": self.system(user_id, now, facts, advice) + note}] + msgs[-12:]
        ctx = {"user_id": user_id, "now": now, "text": text, "turn": self.turn}
        reply = ""
        for _ in range(MAX_TOOL_ROUNDS):
            t0 = time.monotonic()
            msg, meta = self.llm.chat(convo, self.tools.schemas())
            calls = msg.tool_calls or []
            steps.append({"step": "4 think", "model": meta["model"], "said": msg.content,
                          "tool_calls": [c.function.name for c in calls], "ms": ms(t0)})
            if not calls:
                reply = (msg.content or "").strip()
                break
            convo.append({"role": "assistant", "content": msg.content,
                          "tool_calls": [{"id": c.id, "type": "function",
                                          "function": {"name": c.function.name, "arguments": c.function.arguments}} for c in calls]})
            for c in calls:
                t0 = time.monotonic()
                try:
                    args = json.loads(c.function.arguments or "{}")
                    result = self.tools.run(c.function.name, args, ctx)
                except json.JSONDecodeError:
                    args, result = None, {"error": "arguments were not valid JSON"}
                kind = "6 confirm" if c.function.name in ("request_confirmation", "place_order") else "5 act"
                steps.append({"step": kind, "tool": c.function.name, "args": args, "result": result, "ms": ms(t0)})
                convo.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps(result, ensure_ascii=False)})
        else:
            reply = "عذراً، صار في مشكلة. رح أحاول مرة ثانية." if self.store.users[user_id]["lang"] != "en" else "Sorry, something went wrong."
        msgs.append({"role": "assistant", "content": reply})

        ok, why = g.safe_to_remember(text)  # local check, instant
        if ok:  # the AgentCore / Mem0 write happens after the reply goes out, so the user doesn't wait for it
            BACKGROUND.submit(self.memory.learn, user_id, text)
        else:
            self.store.log(user_id, "guardrail", now, check="memory", ok=False, reason=why)
        steps.append({"step": "7 learn (memory)", "stored": "in background" if ok else False, "reason": "ok" if ok else why})
        return {"reply": reply, "steps": steps, "ms": ms(start)}

    def reminder(self, user_id, now):
        """Proactive voice note when items run out (bandit picks the style, uplift decides the offer)."""
        self.memory.seed(user_id)
        advice, full, reason = self.layer.reminder(user_id, now)
        if not advice:
            return {"reply": None, "blocked": reason, "advice": full}
        u = self.store.users[user_id]
        offer = (f"{advice['offer']['discount_pct']}% off if they order now (max {advice['offer']['max_jod']} JOD)"
                 if advice["offer"] and advice["running_out"] else "none, do not mention discounts")
        lang = "Jordanian Arabic dialect" if u["lang"] == "ar" else "Jordanian Arabic with a few English words"
        text = prompt("reminder", name=f"{u['name']} ({u['name_ar']})", items=self.reminder_items(advice),
                      style=advice["style"], style_hint=advice["style_hint"], offer=offer,
                      confirmer=u["confirm_by"], lang_rule=lang)
        msg, meta = self.llm.chat([{"role": "system", "content": text}])
        reply = (msg.content or "").strip()
        self.layer.record_reminder(user_id, now, advice)
        self.history.setdefault(user_id, []).append({"role": "assistant", "content": reply})
        return {"reply": reply, "advice": advice, "model": meta["model"]}

    @staticmethod
    def reminder_items(advice):
        parts = []
        if advice["running_out"]:
            parts.append("groceries running out: " + short(advice["running_out"]))
        if advice.get("usual_box") and advice["usual_box"]["due"]:
            parts.append("their usual Careem Box delivery: " + box_text(advice["usual_box"]))
        if advice.get("usual_ride"):
            parts.append("their usual Careem ride now: " + ride_text(advice["usual_ride"]))
        return "; ".join(parts) or "nothing"

    def family_decision(self, user_id, by, approve, now):
        """The family member answers the confirmation request in their app."""
        if not approve:
            self.store.state["pending"].pop(user_id, None)
            self.store.log(user_id, "confirmation_declined", now, by=by)
            return {"status": "declined"}
        if hasattr(self.tools, "family_checkout"):  # real Careem MCP: checkout behind the same gate
            return self.tools.family_checkout(user_id, by, now)
        ok, reason = g.can_place_order(self.store, user_id, by)
        self.store.log(user_id, "guardrail", now, check="place_order", ok=ok, reason=reason)
        if not ok:
            return {"status": "blocked", "reason": reason}
        if self.store.state["pending"][user_id].get("tool"):  # a Careem checkout proposed through MCP
            return self.tools.execute_pending(user_id, by, now)
        return {"status": "ordered", "order": self.store.place_order(user_id, by, now)}

"""The brain: 7 steps per user message (hear, remember, advise, think, act, confirm, learn)."""
import json
from pathlib import Path

from .personalization import guardrails as g

PROMPTS = Path(__file__).resolve().parent / "prompts"
MAX_TOOL_ROUNDS = 6


def prompt(file, **kw):
    text = (PROMPTS / f"{file}.txt").read_text(encoding="utf-8")
    for k, v in kw.items():
        text = text.replace("{" + k + "}", str(v))
    return text


def short(items):
    return ", ".join(f"{p['name_en']} / {p['name_ar']} (usual qty {p.get('usual_qty', 1)}, item_id {p['item_id']})" for p in items) or "nothing"


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
                      style=advice["style"], style_hint=advice["style_hint"], offer=offer)

    def handle(self, user_id, text, now):
        self.turn += 1
        steps = [{"step": "1 hear", "text": text}]
        self.memory.seed(user_id)

        facts = self.memory.recall(user_id, text)
        steps.append({"step": "2 remember", "facts": [f["fact"] for f in facts]})

        advice = self.layer.advise(user_id, now)
        open_reminder = [e for e in self.store.events(user_id, "reminder") if "reply" not in e]
        note = ""
        if open_reminder:  # the user's answer to our reminder is the bandit's reward
            reply = "no" if g.says_no(text) else "yes" if g.says_yes(text) else None
            if reply:
                self.layer.feedback(user_id, reply, now)
                steps.append({"step": "7 learn (reward)", "reminder_style": open_reminder[-1]["style"], "reply": reply})
                if reply == "yes":
                    note = ("\nThe user just said yes to your reminder about: " + short(advice["running_out"])
                            + ". Add those items to the cart and request confirmation from the family member who usually confirms.")
        steps.append({"step": "3 advise", "running_out": [p["item_id"] for p in advice["running_out"]],
                      "style": advice["style"], "offer": advice["offer"], "offer_decision": advice["offer_decision"]})

        msgs = self.history.setdefault(user_id, [])
        msgs.append({"role": "user", "content": text})
        convo = [{"role": "system", "content": self.system(user_id, now, facts, advice) + note}] + msgs[-12:]
        ctx = {"user_id": user_id, "now": now, "text": text, "turn": self.turn}
        reply = ""
        for _ in range(MAX_TOOL_ROUNDS):
            msg, meta = self.llm.chat(convo, self.tools.schemas())
            calls = msg.tool_calls or []
            steps.append({"step": "4 think", "model": meta["model"], "said": msg.content,
                          "tool_calls": [c.function.name for c in calls]})
            if not calls:
                reply = (msg.content or "").strip()
                break
            convo.append({"role": "assistant", "content": msg.content,
                          "tool_calls": [{"id": c.id, "type": "function",
                                          "function": {"name": c.function.name, "arguments": c.function.arguments}} for c in calls]})
            for c in calls:
                try:
                    args = json.loads(c.function.arguments or "{}")
                    result = self.tools.run(c.function.name, args, ctx)
                except json.JSONDecodeError:
                    args, result = None, {"error": "arguments were not valid JSON"}
                kind = "6 confirm" if c.function.name in ("request_confirmation", "place_order") else "5 act"
                steps.append({"step": kind, "tool": c.function.name, "args": args, "result": result})
                convo.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps(result, ensure_ascii=False)})
        else:
            reply = "عذراً، صار في مشكلة. رح أحاول مرة ثانية." if self.store.users[user_id]["lang"] != "en" else "Sorry, something went wrong."
        msgs.append({"role": "assistant", "content": reply})

        stored, why = self.memory.learn(user_id, text)
        steps.append({"step": "7 learn (memory)", "stored": stored, "reason": why})
        if not stored and why.startswith("sensitive"):
            self.store.log(user_id, "guardrail", now, check="memory", ok=False, reason=why)
        return {"reply": reply, "steps": steps}

    def reminder(self, user_id, now):
        """Proactive voice note when items run out (bandit picks the style, uplift decides the offer)."""
        self.memory.seed(user_id)
        advice, full, reason = self.layer.reminder(user_id, now)
        if not advice:
            return {"reply": None, "blocked": reason, "advice": full}
        u = self.store.users[user_id]
        offer = (f"{advice['offer']['discount_pct']}% off if they order now (max {advice['offer']['max_jod']} JOD)"
                 if advice["offer"] else "none, do not mention discounts")
        lang = "Jordanian Arabic dialect" if u["lang"] == "ar" else "Jordanian Arabic with a few English words"
        text = prompt("reminder", name=f"{u['name']} ({u['name_ar']})", items=short(advice["running_out"]),
                      style=advice["style"], style_hint=advice["style_hint"], offer=offer,
                      confirmer=u["confirm_by"], lang_rule=lang)
        msg, meta = self.llm.chat([{"role": "system", "content": text}])
        reply = (msg.content or "").strip()
        self.layer.record_reminder(user_id, now, advice)
        self.history.setdefault(user_id, []).append({"role": "assistant", "content": reply})
        return {"reply": reply, "advice": advice, "model": meta["model"]}

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
        return {"status": "ordered", "order": self.store.place_order(user_id, by, now)}

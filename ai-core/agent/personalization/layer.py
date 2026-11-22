"""The personalization layer: learn -> predict -> decide -> speak, every action through the guardrails."""
from . import guardrails as g
from .bandit import STYLES, ReminderBandit, context_vector
from .repurchase import due_items, predictions, similar_user_staples
from . import services
from .uplift import MIN_UPLIFT, OFFER, OfferModel
from ..store import parse_ts


class PersonalizationLayer:
    def __init__(self, store):
        self.store = store
        self.bandit = ReminderBandit(store.state_dir)
        self.offers = OfferModel(store.state_dir)
        self.services = services.load()

    def context(self, user_id, now, n_due):
        u = self.store.users[user_id]
        last = max((parse_ts(o["ts"]) for o in self.store.orders(user_id)), default=None)
        days_since = (now - last).days if last else 30
        return context_vector(now.hour, u.get("age", 65), n_due, days_since, u.get("lang") != "en")

    def advise(self, user_id, now):
        """Predict + decide. Returns the advice the LLM gets in its prompt (it never computes these itself)."""
        due = due_items(self.store, user_id, now)
        cold = len(self.store.orders(user_id)) < 3
        ctx = self.context(user_id, now, len(due))
        style, expectations = self.bandit.choose(ctx)
        uplift, feats = self.offers.uplift(self.store, user_id, now)
        offer_ok, offer_reason = g.can_offer(self.store, user_id, now)
        give_offer = offer_ok and uplift >= MIN_UPLIFT
        return {
            "running_out": [{k: p[k] for k in ("item_id", "name_en", "name_ar", "usual_qty", "days_since",
                                                "median_gap_days", "due_score")} for p in due],
            "cold_start": cold,
            "usual_ride": services.usual_ride(self.services, user_id, now),
            "usual_box": services.usual_box(self.services, user_id, now),
            "suggestions_for_new_user": similar_user_staples(self.store, user_id) if cold else [],
            "style": style, "style_hint": STYLES[style], "style_scores": expectations, "context": ctx,
            "offer": dict(OFFER) if give_offer else None,
            "offer_decision": {"uplift": round(uplift, 3), "threshold": MIN_UPLIFT, "features": feats,
                               "allowed": offer_ok, "reason": offer_reason if not offer_ok else
                               ("uplift above threshold" if give_offer else "would likely order anyway / offer changes little")},
        }

    def reminder(self, user_id, now):
        """Proactive reminder: only if the guardrails allow and something is running out."""
        ok, reason = g.can_remind(self.store, user_id, now)
        advice = self.advise(user_id, now)
        due_box = advice.get("usual_box") and advice["usual_box"]["due"]
        if ok and not (advice["running_out"] or due_box or advice.get("usual_ride")):
            ok, reason = False, "nothing is running out and no usual ride or Box delivery is due"
        if not ok:
            self.store.log(user_id, "guardrail", now, check="reminder", ok=False, reason=reason)
            return None, advice, reason
        return advice, advice, "ok"

    def record_reminder(self, user_id, now, advice):
        """Called once the voice note was actually written, so a failed send does not use up today's reminder."""
        self.store.log(user_id, "reminder", now, style=advice["style"], context=advice["context"],
                       items=[p["item_id"] for p in advice["running_out"]], offer=advice["offer"])
        if advice["offer"]:
            self.store.log(user_id, "offer", now, offer=advice["offer"], uplift=advice["offer_decision"]["uplift"])

    def feedback(self, user_id, reply, now):
        """Learn: the reply to the last reminder (yes / no / silence) is the bandit's reward."""
        rem = [e for e in self.store.events(user_id, "reminder") if "reply" not in e]
        if not rem:
            return None
        ev = rem[-1]
        self.bandit.update(ev["style"], reply, ev["context"])
        ev["reply"] = reply
        self.store.log(user_id, "reward", now, style=ev["style"], reply=reply)
        return ev

    def snapshot(self, user_id, now):
        return {"predictions": predictions(self.store, user_id, now), "advice": self.advise(user_id, now)}

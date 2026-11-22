"""Guardrails: checked before anything is said or done. Each check returns (ok, reason)."""
import datetime as dt
import re

from ..store import parse_ts

SPEND_CAP_JOD = 30.0
QUIET_HOURS = (22, 8)  # no reminders from 22:00 to 08:00
OFFER_EVERY_DAYS = 7
YES = re.compile(r"\b(yes|yeah|ok|okay|sure|order it|go ahead|confirm)\b|نعم|اه|آه|أه|ايوا|إيوا|ايوه|تمام|اطلب|اطلبه|اطلبها|ماشي|يلا|موافق|اكيد|أكيد", re.I)
# sensitive details are never stored unless the user chose to share them for ordering
SENSITIVE = re.compile(
    r"\b\d{9,}\b|password|passcode|pin code|credit card|iban|diabet|cancer|depress|pregnan|"
    r"كلمة السر|رقم الوطني|الرقم الوطني|بطاقة|فيزا|سكري|السكري|سرطان|اكتئاب|حامل|ضغط الدم", re.I)


def can_remind(store, user_id, now):
    if now.hour >= QUIET_HOURS[0] or now.hour < QUIET_HOURS[1]:
        return False, f"quiet hours ({QUIET_HOURS[0]}:00-{QUIET_HOURS[1]:02d}:00)"
    if any(parse_ts(e["ts"]).date() == now.date() for e in store.events(user_id, "reminder")):
        return False, "already reminded today (max 1 per day)"
    return True, "ok"


def can_offer(store, user_id, now):
    last = [parse_ts(e["ts"]) for e in store.events(user_id, "offer")]
    if last and now - max(last) < dt.timedelta(days=OFFER_EVERY_DAYS):
        return False, f"an offer was given in the last {OFFER_EVERY_DAYS} days"
    return True, "ok"


def allowed_confirmers(store, user_id):
    u = store.users[user_id]
    return [u["name"]] + [f["name"] for f in u["family"] if f.get("can_confirm")]


def can_place_order(store, user_id, confirmed_by, user_text=None):
    cart = store.cart_view(user_id)
    if not cart["lines"]:
        return False, "the cart is empty"
    if cart["total_jod"] > SPEND_CAP_JOD:
        return False, f"total {cart['total_jod']} JOD is over the {SPEND_CAP_JOD} JOD cap; a family member must confirm in the app"
    if confirmed_by not in allowed_confirmers(store, user_id):
        return False, f"{confirmed_by} is not allowed to confirm orders for this user"
    if not store.state["pending"].get(user_id):
        return False, "ask for confirmation first (request_confirmation), then wait for the answer"
    if confirmed_by == store.users[user_id]["name"] and not (user_text and YES.search(user_text)):
        return False, "the user has not said yes in this message"
    return True, "ok"


def safe_to_remember(text):
    m = SENSITIVE.search(text)
    return (False, f"sensitive detail ('{m.group(0)}') is not stored") if m else (True, "ok")

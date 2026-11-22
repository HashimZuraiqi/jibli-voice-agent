"""Guardrails: checked before anything is said or done. Each check returns (ok, reason)."""
import datetime as dt
import math
import re

from ..store import parse_ts

SPEND_CAPS = {"JOD": 50.0, "AED": 259.0}  # per order, about 50 JOD each (team decision); the Careem sandbox prices in AED
SPEND_CAP_JOD = SPEND_CAPS["JOD"]  # careem_mcp.py converts the basket currency to JOD and checks this
QUIET_HOURS = (22, 8)  # no reminders from 22:00 to 08:00
OFFER_EVERY_DAYS = 7
YES_WORDS = {"yes", "yeah", "yep", "yup", "ya", "ok", "okay", "okey", "k", "sure", "confirm", "confirmed", "alright",
             "fine", "absolutely", "definitely", "ofc", "yalla",
             "نعم", "اه", "ايوا", "ايوه", "ايه", "يس", "تمام", "ماشي", "يلا", "موافق", "موافقه", "اكيد", "طبعا", "حاضر",
             "اوكي", "اوك", "خلص", "زبط", "مزبوط", "صح", "منيح", "عال", "اطلب", "اطلبه", "اطلبها", "اطلبلي", "اطلبيه",
             "اطلبوا", "ابعت", "ابعته", "ابعتها", "ابعتلي", "بعته", "بعتها", "اكد", "اكده", "اكدها"}
YES_PHRASES = (("order", "it"), ("go", "ahead"), ("do", "it"), ("of", "course"), ("sounds", "good"), ("please", "do"),
               ("send", "it"), ("why", "not"))
# "no problem" style phrases say yes even though they hold a negation word
NO_PROBLEM = (("ما", "في", "مشكله"), ("مافي", "مشكله"), ("مش", "مشكله"), ("ولا", "يهمك"), ("no", "problem"),
              ("not", "a", "problem"))
NO_WORDS = {"no", "not", "nope", "nah", "never", "dont", "don't", "cancel", "later", "stop", "wait", "hold",
            "لا", "لاء", "مش", "مو", "ما", "بلاش", "بعدين", "الغي", "الغاء", "وقف", "استنى", "مابدي"}
# "yes, but change something" is not a yes to the order as it stands: ask again
CONDITIONS = {"but", "except", "change", "remove", "instead", "بس", "غير", "شيل", "شيلي", "بدل", "غيرها", "غيره"}


def tokens(text):
    """One normalization for both checks: no diacritics, one alef/hamza form, punctuation (incl. ، ؛ ؟) dropped."""
    t = re.sub(r"[\u064B-\u0652\u0640]", "", (text or "").lower())
    t = re.sub(r"[أإآ]", "ا", t).replace("ى", "ي").replace("ة", "ه").replace("لأ", "لا")
    return re.findall(r"[a-z']+|[\u0621-\u064A]+|\d+", t)


def _drop_phrases(toks, phrases):
    out, i = [], 0
    while i < len(toks):
        hit = next((p for p in phrases if tuple(toks[i:i + len(p)]) == p), None)
        if hit:
            out.append("<yes>")
            i += len(hit)
        else:
            out.append(toks[i])
            i += 1
    return out


def says_no(text):
    return any(w in NO_WORDS for w in _drop_phrases(tokens(text), NO_PROBLEM))


def says_yes(text):
    """Any kind of yes, in any length: a yes word or phrase ("اه والله اطلبه", "sure, go ahead", "ما في مشكلة"),
    unless the message also says no / wait, or asks to change something first ("اه بس شيل الرز")."""
    toks = _drop_phrases(tokens(text), NO_PROBLEM)
    if not toks or any(w in NO_WORDS or w in CONDITIONS for w in toks):
        return False
    pairs = set(zip(toks, toks[1:]))
    return "<yes>" in toks or any(w in YES_WORDS for w in toks) or any(p in pairs for p in YES_PHRASES)


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
    pending = store.state["pending"].get(user_id)
    if not pending and not store.cart(user_id):
        return False, "nothing is waiting for approval"
    careem = bool(pending and pending.get("tool"))  # a proposed Careem checkout (agent/careem.py)
    if careem:
        total, currency = pending["total"], pending.get("currency", "AED")
    else:
        cart = store.cart_view(user_id)
        if not cart["lines"]:
            return False, "the cart is empty"
        total, currency = cart["total_jod"], "JOD"
    if currency not in SPEND_CAPS:  # fail closed: an unknown currency has no cap we can check
        return False, f"unknown currency {currency!r}; a family member must confirm in the app"
    cap = SPEND_CAPS[currency]
    try:
        bad_total = not (math.isfinite(float(total)) and 0 < float(total))
    except (TypeError, ValueError):
        bad_total = True
    if bad_total:  # fail closed: NaN or a missing price must never pass the cap
        return False, f"the total {total!r} is not a real price"
    if not float(total) <= cap:
        return False, f"total {total} {currency} is over the {cap} {currency} cap; a family member must confirm in the app"
    if confirmed_by not in allowed_confirmers(store, user_id):
        return False, f"{confirmed_by} is not allowed to confirm orders for this user"
    if not pending:
        return False, "ask for confirmation first (request_confirmation), then wait for the answer"
    if pending["by"] != confirmed_by:
        return False, f"confirmation was requested from {pending['by']}, not {confirmed_by}"
    if not careem and pending.get("cart") != cart:
        return False, "the cart changed after confirmation was requested; ask again"
    if confirmed_by == store.users[user_id]["name"] and not says_yes(user_text):
        return False, "the user has not clearly said yes in this message"
    return True, "ok"


def safe_to_remember(text):
    m = SENSITIVE.search(text)
    return (False, f"sensitive detail ('{m.group(0)}') is not stored") if m else (True, "ok")

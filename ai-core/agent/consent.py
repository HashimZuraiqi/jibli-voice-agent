"""Did the user agree to the waiting order? A fast word check first, then Claude reads the meaning."""
import json
import re
from pathlib import Path

from .personalization import guardrails as g

PROMPT = Path(__file__).resolve().parent / "prompts" / "consent.txt"


def judge(llm, text, asked):
    """'yes', 'no' or 'unclear' for the user's reply to `asked` (what is waiting for her answer).

    A question is never a yes. If the LLM is unavailable, only the word check decides, and anything it cannot
    read as a clear yes is 'unclear', so Jibli asks again rather than ordering."""
    if not text or not text.strip() or "?" in text or "؟" in text:
        return "unclear"
    if g.says_yes(text):
        return "yes"
    negated = g.says_no(text)
    blocked = g.blocks_yes(text)  # no / wait words, conditions, question words: the LLM may never make these a yes
    if llm is None:
        return "no" if negated else "unclear"
    try:
        data = json.dumps({"ORDER": (asked or "an order")[:300], "REPLY": text[:500]}, ensure_ascii=False)
        msg, _ = llm.chat([{"role": "system", "content": PROMPT.read_text(encoding="utf-8")},
                           {"role": "user", "content": data}])
        words = re.findall(r"[A-Za-z]+", (msg.content or "").upper())
    except Exception:  # LLM down or keys expired: never guess a yes
        return "no" if negated else "unclear"
    verdict = {"YES": "yes", "NO": "no"}.get(words[0] if words else "", "unclear")
    return "unclear" if verdict == "yes" and blocked else verdict

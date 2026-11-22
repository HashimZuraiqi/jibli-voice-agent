# Sanad — voice ordering agent: LLM brain + personalization layer

Older users in Jordan order Careem Quik groceries by voice note; a family member confirms. This part is the **brain**
(LLM + tools) and the **personalization layer** (memory, repurchase prediction, bandit, uplift offers, guardrails).
Speech-to-text / text-to-speech are not here: you type the transcribed text, and the reply is the text a TTS would speak.
Careem's services are mocked with local data. Design notes: `CLAUDE.md`.

## Run

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                       # paste the AWS export values from link.careem.com/htjordan
.venv/bin/python data/generate.py          # mock data relative to today (run again on demo day)
.venv/bin/python -m uvicorn web.app:app --port 8000
# open http://127.0.0.1:8000
.venv/bin/python -m pytest -q              # tests, no LLM needed
```

The first start downloads the multilingual embedding model (~220 MB, once).

## Demo script

1. **Um Khaled** — click *Send proactive reminder*: the layer sees milk, bread and tea running out, LinUCB picks the
   style, uplift says no discount (she orders anyway), and Sanad sends a Jordanian-Arabic voice note.
2. Type `اه يا ريت` — her yes is the bandit's reward; Sanad fills the cart and asks Khaled to confirm.
   Click *Approve* as Khaled → the order is placed and joins her history.
3. Type `شو بتعرف عني؟` → Sanad lists what it remembers; click × to delete a fact.
4. Type `جوزي ما بوكل سكر، وابني خالد هو اللي بدفع` → Mem0 stores the facts.
   Type `رقمي الوطني 9851234567` → the guardrail refuses to store it (see the log).
5. Set *Time* to 23:00 and send a reminder → blocked by quiet hours. Send two reminders at 10:00 → the second is blocked.
6. **Hajjeh Fatima** (new user) — cold start: no history, suggestions from similar users, and uplift gives her an offer.

## Quota

Default LLM is Claude on Bedrock (team account, $300 cap, credentials expire hourly). The notes below apply only to `LLM_PROVIDER=openrouter`.

The OpenRouter free tier is **50 requests per day per account**. One chat message uses about 2–5 calls
(the agent's tool rounds + Mem0 fact extraction). Set `MEM0_INFER=false` in `.env` to save calls, or add $10 credit
once for 1,000 free requests/day.

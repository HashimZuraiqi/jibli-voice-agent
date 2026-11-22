# Sanad — voice ordering agent: LLM brain + personalization layer

Older users in Jordan order Careem Quik groceries by voice note; a family member confirms. This part is the **brain**
(LLM + tools) and the **personalization layer** (memory, repurchase prediction, bandit, uplift offers, guardrails).
Speech-to-text / text-to-speech are not here: you type the transcribed text, and the reply is the text a TTS would speak.
Careem's services are mocked with local data. Design notes: `CLAUDE.md`.

## Run

```bash
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env                       # paste the AWS export values from link.careem.com/htjordan
.venv/bin/python scripts/create_agentcore_memory.py   # once per AWS account: paste AGENTCORE_MEMORY_ID into .env
.venv/bin/python data/generate.py          # mock data relative to today (run again on demo day)
.venv/bin/python -m uvicorn web.app:app --port 8000
# open http://127.0.0.1:8000
.venv/bin/python -m pytest -q              # tests, no LLM needed
```

Memory runs on Amazon Bedrock AgentCore Memory. Backup: `MEMORY_PROVIDER=mem0` in `.env` (local Mem0; its first start downloads a ~220 MB embedding model).

## Demo script

1. **Um Khaled** — click *Send proactive reminder*: the layer sees milk, bread and tea running out, LinUCB picks the
   style, uplift says no discount (she orders anyway), and Sanad sends a Jordanian-Arabic voice note.
2. Type `اه يا ريت` — her yes is the bandit's reward; Sanad fills the cart and asks Khaled to confirm.
   Click *Approve* as Khaled → the order is placed and joins her history.
3. Type `شو بتعرف عني؟` → Sanad lists what it remembers; click × to delete a fact.
4. Type `جوزي ما بوكل سكر، وابني خالد هو اللي بدفع` → AgentCore Memory stores the facts.
   Type `رقمي الوطني 9851234567` → the guardrail refuses to store it (see the log).
5. Set *Time* to 23:00 and send a reminder → blocked by quiet hours. Send two reminders at 10:00 → the second is blocked.
6. **Hajjeh Fatima** (new user) — cold start: no history, suggestions from similar users, and uplift gives her an offer.

## Real Careem MCP

- **Sandbox (build + test, never orders):** build it once from https://builders.careem.com/sandbox/careem-mcp-sandbox.zip
  (outside this repo), then `CAREEM_PROVIDER=mcp`, `CAREEM_MCP_URL=http://127.0.0.1:8787/mcp`, no token. Fake Dubai data, AED, stateless.
- **Production (REAL Careem account, REAL orders and money):** `.venv/bin/python scripts/careem_login.py` signs in and
  writes `CAREEM_MCP_URL` + `CAREEM_MCP_TOKEN`; `--refresh` renews the token. Then `CAREEM_PROVIDER=mcp`.

Restart after switching. The agent uses Careem's own
tool list; `cart_grocery_checkout` is hidden from the LLM and only runs after a human yes (once, never retried).
If the MCP server can't be reached at start, the app prints why and uses the mock tools.

## Quota

Default LLM is Claude on Bedrock (team account, $300 cap, credentials expire hourly). The notes below apply only to `LLM_PROVIDER=openrouter`.

The OpenRouter free tier is **50 requests per day per account**. One chat message uses about 2–5 calls
(the agent's tool rounds + Mem0 fact extraction). Set `MEM0_INFER=false` in `.env` to save calls, or add $10 credit
once for 1,000 free requests/day.

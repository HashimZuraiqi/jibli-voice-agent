# Voice Agent — LLM brain + personalization layer

Hackathon project (demo: 2026-11-22). A voice-note ordering agent for Careem Quik, built for older users in Jordan
who order groceries by voice; a family member (e.g. the son who pays) can confirm orders.
Part of the Jibli repo (`ai-core/` folder, branch `ai-core`); runs standalone with mocked Careem data.
Research: [How others built the brain and personalization](https://claude.ai/artifact/4en3B857ATsoHiucSRWwxQ) ·
code docs: [Sanad — Code Documentation](https://claude.ai/artifact/4RW78cQdw1Fa5JvSZRZ263).

**Our scope: the LLM brain and the personalization layer only.** Speech-to-text and text-to-speech are a teammate's
part: here the input is the already-transcribed text, and the output is the text a TTS would speak.
Careem's services come through **careem-mcp** (MCP): a local sandbox built from Careem's spec in `careem-mcp-sandbox/` (groceries, food, cart, Box, user; production-identical tool shapes, fixed sample answers), rides through a local stand-in (not in Careem's public sandbox yet). `CAREEM_PROVIDER` picks the path: `mock` (offline catalog, default), `mcp` (groceries; works with production) or `mcp-all` (every service, `agent/careem.py`).

## Stack

- Python 3.12 venv in `.venv` (`python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt`).
- LLM: **Claude on Amazon Bedrock** (Converse API via `boto3`, `global.anthropic.claude-sonnet-5-5`, us-east-1).
  Credentials come from the environment / default chain, never code; the event's expire hourly, so paste new ones
  into `.env` and the next call reloads them. Fallback: `LLM_PROVIDER=openrouter` (free tier, 50 requests/day).
- Memory: **Amazon Bedrock AgentCore Memory** (default, `agent/agentcore_memory.py`, `MEMORY_PROVIDER=agentcore`):
  actorId = user_id; user messages -> `create_event`, AgentCore's semantic + user-preference strategies extract facts
  into `/users/{actorId}/facts/` and `/users/{actorId}/preferences/`; seed facts via `batch_create_memory_records`;
  recall = `retrieve_memory_records`, list = `list_memory_records`, forget = `delete_memory_record`.
  Create the resource once with `scripts/create_agentcore_memory.py` -> `AGENTCORE_MEMORY_ID` in `.env`.
- Memory backup: **Mem0** (`MEMORY_PROVIDER=mem0`, `mem0ai`), LLM = Bedrock Haiku (or OpenRouter), embedder = **FastEmbed** local multilingual
  (`paraphrase-multilingual-MiniLM-L12-v2`, 384 dims), vector store = local Qdrant in `state/`. Imported only when chosen.
- Bandit: **MABWiser** LinUCB. Uplift: **CausalML** `BaseTClassifier` (control group named `"control"`).
- Web: FastAPI + one static HTML page.
- Mem0 v2 API: `add(..., user_id=...)` but `search(q, filters={"user_id": ...}, top_k=...)` and
  `get_all(filters={"user_id": ...})`; top-level `user_id` in search/get_all raises.

## The brain: 7 steps per user message (`agent/brain.py`)

1. **Hear** — receive the transcribed text (Jordanian Arabic, English or a mix).
2. **Remember** — AgentCore Memory search for facts relevant to the message + the user profile (family, payer, usual basket).
3. **Advise** — the personalization layer returns advice: items running out, whether an offer is worth giving, which style to speak in.
4. **Think** — the LLM reads message + memory + advice and plans (OpenAI-style tool calling).
5. **Act** — tool calls on the mocked Careem services: search catalog, usual basket, cart.
6. **Confirm** — nothing is ordered until the user or the paying family member confirms (guardrail-enforced).
7. **Learn** — the order and new facts go back into memory/order history; the reply is the bandit's reward.

## Personalization layer: learn → predict → decide → speak, with guardrails (`agent/personalization/`)

| Step | Module | What |
|---|---|---|
| Learn | `bandit.py`, `memory.py` | yes / no / silence on a reminder → reward 1 / 0 / 0 → `partial_fit`; facts from messages → Mem0 |
| Predict | `repurchase.py` | per user × item median gap between purchases; due score = days since last / median gap (≥ 0.9 = running out) |
| Decide | `bandit.py`, `uplift.py` | LinUCB picks the reminder style; the T-learner gives the offer only if predicted uplift ≥ threshold and budget allows |
| Speak | `layer.py` → brain | advice is handed to the LLM, which writes the voice-note text in that style and the user's dialect |
| Guardrails | `guardrails.py` | checked on every action before anything is said or done (below) |

Guardrails: no order without confirmation by the user or an allowed family member; spend cap per order;
no reminders 22:00–08:00 and at most 1 per day; offer at most 1 per week; never store sensitive data in memory
(health, religion, finances beyond "who pays", ID numbers) unless the user asked to; "what do you know about me?"
lists memory and "forget …" deletes it.

Cold start: a new user gets the bandit prior trained on synthetic logs of similar users and default
reorder gaps per item category (`data/catalog.json` `default_gap_days`).

## Layout

```
agent/llm.py            Bedrock Converse client (OpenRouter fallback), same OpenAI-style return shape
agent/tools.py          mocked Careem tools (catalog, usual basket, cart, confirm, place order) = default/backup
agent/careem_mcp.py     real Careem MCP (CAREEM_PROVIDER=mcp): only an allow-list of grocery/read tools reaches the
                        LLM; cart_grocery_checkout only via the confirm gate (total_price from the confirmed basket,
                        once, never retried). Sandbox http://127.0.0.1:8787/mcp (fake Dubai data, no token);
                        production https://mcp.careemapis.com/mcp = REAL account, orders, money
agent/memory.py         make_memory(): AgentCore (default) or Mem0 backup + seed facts
agent/agentcore_memory.py  AgentCore Memory backend
scripts/                create_agentcore_memory.py (run once), careem_login.py (production OAuth token)
agent/careem.py         Careem MCP for all services (CAREEM_PROVIDER=mcp-all): groceries, food, Box, rides stand-in;
                        the LLM proposes the exact checkout, it runs once after a human yes
agent/personalization/  repurchase, services (usual ride / Box), bandit, uplift, guardrails, layer
careem-mcp-sandbox/     local careem-mcp server from Careem's spec + its CLI and acceptance tests
agent/brain.py          the 7-step loop
data/                   generate.py → catalog, users, orders, synthetic bandit + uplift logs
web/app.py, web/index.html   chat page + side panel (memory, due items, bandit choice, offer, guardrail log)
tests/                  personalization tests, no LLM needed
state/                  runtime state (Mem0/Qdrant, bandit pickle, carts); git-ignored, delete to reset
```

## Conventions

- Keep it small and demo-ready: no feature nobody asked for.
- Every LLM-free part (repurchase, bandit, uplift, guardrails, tools) has a test in `tests/`; run
  `.venv/bin/python -m pytest -q` before saying something works.
- Prompts live in `agent/prompts/*.txt`.
- Deterministic: temperature 0, fixed seeds for bandit, uplift and data generation.

## Careem MCP rules

- The LLM never gets the spending tools (`cart_grocery_checkout`, `cart_checkout`, `box_create_order`, `rides_request`).
  It proposes the exact call with `request_confirmation`; `CareemTools.execute_pending` runs it once after the user's
  clear yes (later message) or the family's approval, and never retries a failed checkout.
- A new cart or quote cancels a pending confirmation only for the same service.
- Spend cap per currency (`SPEND_CAPS`: 30 JOD, 150 AED). The sandbox world is Dubai / AED; production in Amman is JOD.
- With `CAREEM_PROVIDER=mcp-all`, start the sandbox before the app: `.venv/bin/python careem-mcp-sandbox/careem_mcp.py start`.

# Jibli (جيبلي) — voice ordering agent: LLM brain + personalization layer

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
   style, uplift says no discount (she orders anyway), and Jibli sends a Jordanian-Arabic voice note.
2. Type `اه يا ريت` — her yes is the bandit's reward; Jibli fills the cart and asks Khaled to confirm.
   Click *Approve* as Khaled → the order is placed and joins her history.
3. Type `شو بتعرف عني؟` → Jibli lists what it remembers; click × to delete a fact.
4. Type `جوزي ما بوكل سكر، وابني خالد هو اللي بدفع` → AgentCore Memory stores the facts.
   Type `رقمي الوطني 9851234567` → the guardrail refuses to store it (see the log).
5. Set *Time* to 23:00 and send a reminder → blocked by quiet hours. Send two reminders at 10:00 → the second is blocked.
6. **Hajjeh Fatima** (new user) — cold start: no history, suggestions from similar users, and uplift gives her an offer.

## Voice page and family page (demo)

- **Elder:** http://127.0.0.1:8000/voice/um_khaled — one big mic button (tap to talk, tap to stop), the reply is
  spoken back, big نعم / لا when an order waits for her, and a text box ("speak it or type it, same agent").
- **Family:** http://127.0.0.1:8000/family/um_khaled — open on Khaled's phone: the basket and total waiting for
  approval, وافق / رفض. When the agent asks her, she OR Khaled can confirm, whoever is first (placed once).
- Speech: `STT_PROVIDER` / `TTS_PROVIDER` in `.env` (see `.env.example`). Quickest working mic: `STT_PROVIDER=browser`
  (Edge/Chrome speech recognition in Jordanian Arabic, no install, needs internet; `?lang=ar-SA` to change). Anas's functions plug in without code changes:
  `STT_PROVIDER=func`, `STT_FUNC=stt.anas:stt` (`stt(audio_bytes) -> text`), `TTS_PROVIDER=func`,
  `TTS_FUNC=stt.anas:tts` (`tts(text) -> audio_bytes`). Without them: local Whisper (`pip install openai-whisper`
  + ffmpeg) and the browser's own Arabic voice. **Open the voice page in Microsoft Edge**: it has online natural
  Jordanian voices (ar-JO), which the page prefers; `?voice=Taim` picks one by name. Amazon Polly is blocked for the
  event's AWS role (AccessDenied), so don't use `TTS_PROVIDER=polly` there.
- Levantine voice option: **Leva-TTS** runs as its own small server in a separate venv (`stt/leva_server.py`, setup in
  its header), then `TTS_PROVIDER=func`, `TTS_FUNC=stt.leva:tts`. Weights are non-commercial: demo only. If the
  server is down, the page falls back to the browser voice. The recording is never stored.
- The phone must reach the laptop: use the laptop's LAN IP (`--host 0.0.0.0`). Browsers only allow the mic on
  http://localhost or https, so run the elder page on the laptop itself.

## Demo sandbox: Amman mode

Careem's sandbox always returns the same Dubai test basket in AED. For the demo, run the in-repo sandbox in Amman
mode: the grocery tools build the cart she actually asked for from Jibli's Jordanian catalog (`data/catalog.json`),
priced in JOD, delivered to an Amman address. Same tool names and response shapes; nothing is ever ordered.

```bash
.venv/bin/python careem-mcp-sandbox/careem_mcp.py stop            # if another sandbox is on :8787
.venv/bin/python careem-mcp-sandbox/careem_mcp.py start --amman
```
`.env`: `CAREEM_PROVIDER=mcp`, `CAREEM_MCP_URL=http://127.0.0.1:8787/mcp`, `SANDBOX_WORLD=amman`, and remove
`CAREEM_LAT`/`CAREEM_LNG` (the Amman address comes from `user_info`). Pitch line: "Careem's MCP tools on a local
sandbox built from Careem's spec, with our Amman test data".

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

# Tasks

- [ ] 1. Voice in: record button → STT → agent (Anas)
  - [ ] 1.1 Record page posts audio; STT (Whisper or Cohere) returns the transcript
  - [ ] 1.2 Transcript goes to `POST /api/chat`; reply text goes to TTS
  - _Requirements: 1.1, 1.2, 1.3_

- [ ] 2. Build the cart through Careem MCP
  - [x] 2.1 MCP connector on SDK 2.x, bearer token, one short connection per call (`ai-core/agent/careem_mcp.py`)
  - [x] 2.2 Allow-listed server tools to the agent; mocks stay the default/backup (`make_tools`)
  - [x] 2.3 lat/lng filled in on every call (saved address, else `CAREEM_LAT`/`CAREEM_LNG`)
  - [x] 2.4 Tests: fake connector (`test_careem_mcp.py`) and the real connector against an in-process server (`test_integrations.py`)
  - [ ] 2.5 Run one journey on the local sandbox (`CAREEM_MCP_URL=http://127.0.0.1:8787/mcp`), then decide on production
  - _Requirements: 2.1–2.6_

- [ ] 3. Read-back of items, total and address
  - [x] 3.1 Keep the `cart_get_basket_price` result as the basket the gate confirms
  - [x] 3.2 Prompt: user_info first, cart with quantities, price, then request_confirmation
  - [ ] 3.3 Check the spoken read-back (items, total, address) on a real basket and with TTS
  - _Requirements: 3.1, 3.2_

- [ ] 4. Confirm gate before checkout
  - [x] 4.1 `cart_grocery_checkout` never offered to the LLM; only `place_order` / `family_checkout` reach it
  - [x] 4.2 Clear yes in a later message; family approval only from `/api/family`; cart change cancels; spend cap; unknown total → family
  - [x] 4.3 Checkout arguments from earlier answers; same basket ordered once; failed checkout never retried
  - [ ] 4.4 Ask the organisers whether checkout is real; if not, stay on the sandbox or stop at the basket price
  - [ ] 4.5 Family approval page on the phone (Faris) calls `POST /api/family`
  - _Requirements: 4.1–4.7_

- [ ] 5. Memory with Mem0
  - [x] 5.1 Mem0 with Haiku on Bedrock for fact extraction, temperature stripped (`ai-core/agent/memory.py`)
  - [ ] 5.2 Live check on the demo laptop: tell it a preference, ask "what do you know about me?", then forget
  - _Requirements: 5.1, 5.2, 5.3, 5.4_

- [ ] 6. Claude on Bedrock
  - [x] 6.1 Bedrock Converse client, `global.anthropic.claude-sonnet-5-5`, no temperature, credential reload (`ai-core/agent/llm.py`)
  - [ ] 6.2 Live turn on the demo laptop with fresh AWS values
  - [ ] 6.3 Deploy on AgentCore Runtime (stretch)
  - _Requirements: 6.1, 6.2_

- [ ] 7. Feature freeze at 16:00: record the backup screen recording of the full flow

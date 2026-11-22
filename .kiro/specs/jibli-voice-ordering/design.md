# Design: Jibli voice ordering

## Overview

```
record button ─► stt/ (Whisper or Cohere) ─► ai-core agent ─► Careem MCP ─► confirm gate ─► checkout
                                              │  Claude on Bedrock (OpenRouter fallback)
                                              │  Mem0 memory (Haiku on Bedrock extracts facts)
                                              └─► reply text ─► TTS read-back
```

The agent lives in `ai-core/` (Python 3.12, FastAPI). One message runs 7 steps in `agent/brain.py`:
hear → remember → advise → think → act → confirm → learn.

## Components

| Component | File | Notes |
|---|---|---|
| LLM | `ai-core/agent/llm.py` | `BedrockLLM`: boto3 Converse, `global.anthropic.claude-sonnet-5-5`, no `temperature` (Sonnet 5.5 rejects it); reloads `.env` when the hourly event credentials expire. `LLM_PROVIDER=openrouter` switches to the OpenRouter fallback. |
| Careem MCP | `ai-core/agent/careem_mcp.py` | `MCPConnector`: MCP SDK 2.x `Client`, streamable HTTP (or SSE), bearer token re-read from `.env`. `CareemMCPTools`: allow-listed server tools go to the LLM as the server describes them; lat/lng filled in (saved address, else `CAREEM_LAT`/`CAREEM_LNG`); `cart_grocery_checkout` only behind the gate. `make_tools` falls back to the mocks. |
| Mock tools | `ai-core/agent/tools.py` | Local catalog/cart (`CAREEM_PROVIDER=mock`, default). |
| Memory | `ai-core/agent/memory.py` | `MEMORY_PROVIDER=mem0` (what we demo): Mem0, Haiku on Bedrock extracts facts (temperature stripped), FastEmbed multilingual embeddings, local Qdrant. `agentcore` backend in `agentcore_memory.py` is kept but not used. |
| Personalization | `ai-core/agent/personalization/` | Repurchase prediction, LinUCB reminder style, uplift offers (requirement 7). |
| Web | `ai-core/web/` | Demo page; `/api/chat`, `/api/family` (family approval), `/api/state`. |

## Journey (Careem MCP mode)

1. `user_info` (saved address, lat/lng), `search_groceries_get_top_user_items` / `search_groceries_items`
2. `create_grocery_cart_with_quantities` (clears any pending confirmation)
3. `cart_get_basket_price` → the basket the gate fingerprints
4. Spoken read-back: items, total, address
5. `request_confirmation(by)` → pending, with the basket fingerprint
6. User's clear yes in the next message (`place_order`) or family approval (`/api/family` → `family_checkout`) →
   `check` → `checkout`: arguments from earlier answers, `total_price` from the confirmed basket, called once

## Confirm gate rules (`can_place_order`)

- a pending confirmation exists, from the same person who confirms
- the basket fingerprint matches the one that was confirmed
- total ≤ 30 JOD; unknown total → family only
- the same basket is never ordered twice; a basket whose checkout failed is never retried
- the user's yes is short, clear and not negated (`says_yes`), in a later message
- family approval comes only from the approval page

## Fallbacks

| Fails | Then |
|---|---|
| Bedrock credentials expired | `.env` reloaded once; paste fresh values from link.careem.com/htjordan |
| Careem MCP unset or unreachable at start | mocked catalog and cart |
| Checkout error | not retried; the user checks the Careem app, then a new cart is built |

## Testing

`ai-core/tests/` (no network): guardrails, consent, personalization, Careem MCP gate with a fake connector
(`test_careem_mcp.py`), the real MCP 2.x connector against an in-process server with the Careem tool names
(`test_integrations.py`: lat/lng, unknown total, checkout once), Bedrock message conversion, Mem0 temperature fix.

# Jibli (جيبلي): voice ordering on Careem

> **Private until the demo on Sun 22 Nov 2026 (Careem Builders '26, The ARC, Amman).**
> As of Sat 21 Nov this repo holds only scaffolding and docs. Product code gets written on the day.

Jibli lets anyone order on Careem by sending a voice note in Jordanian Arabic, such as «ابعتلي خبز وحليب وبيض». The agent builds a real Careem grocery cart, reads back the items, total and address by voice, and buys nothing until the user (or a family member who approves and pays) says yes. It learns your usual items ("زي كل مرة"), and next it will remind you before you run out and offer a cheaper deal only when it helps.

- Pitch deck: https://claude.ai/artifact/Pc7w5HzvK1eDssBcyeustV
- UI mockups: https://claude.ai/artifact/6tedq3bC2pBFxiMtgUifgh
- Team brief (schedule, judging, demo script): [docs/team-brief.md](docs/team-brief.md)

## Architecture

```
 [web record button]  /  [WhatsApp (stretch)]
            │  audio
            ▼
        stt/  Whisper or Cohere Transcribe Arabic
            │  text
            ▼
      agent/  Claude on Amazon Bedrock, on AgentCore Runtime
            │  + AgentCore Memory (usual items, preferences)
            ▼
  careem-mcp/ Careem MCP client (groceries)
            │  cart + basket price
            ▼
    backend/  API + CONFIRM GATE ──► family approval page
            │  only after a human "yes"
            ▼
        cart_grocery_checkout   ──► TTS read-back to the user
```

### Careem MCP grocery flow

1. `search_groceries_get_top_user_items` (usual items) and/or `search_groceries_items`
2. `create_grocery_cart_with_quantities`
3. `cart_get_basket_price`
4. **Confirm gate** (user or family says yes, enforced in the backend)
5. `cart_grocery_checkout`

Playbook rules: always pass lat/lng (`user_info` for saved addresses), confirm before spending, never blindly retry checkout or cart changes, expect about 6 chained tool calls.

## Repo layout

| Folder | What goes here | Owner |
|---|---|---|
| `stt/` | Speech to text and TTS (dialect handling) | Anas |
| `agent/` | Claude on Bedrock, AgentCore Runtime + Memory | Hashim |
| `careem-mcp/` | Careem MCP client and the grocery journey | Hashim |
| `backend/` | API, confirm gate, family approval flow | Faris |
| `web/` | Record-button page (the guaranteed demo) and approval page | Anas / Faris |
| `whatsapp/` | Stretch: Twilio sandbox or Meta test number. No Telegram (blocked in Jordan). | Faris |
| `ai-core/` | AI core: LLM brain + personalization layer (memory, repurchase prediction, bandit reminders, uplift offers, guardrails), runnable demo on mocked Careem data. See [ai-core/README.md](ai-core/README.md) | Anas |
| `.kiro/` | Kiro specs (requirements, design, tasks) and steering | Hashim |
| `docs/` | Brief and notes | All |

## Setup

```bash
cp .env.example .env   # fill in locally, never commit .env
```

## Team

- **Hashim Zuraiqi** ([@HashimZuraiqi](https://github.com/HashimZuraiqi)): Bedrock + AgentCore agent, Careem MCP, AWS, Kiro specs
- **Anas Gharaibah** ([@AnasGharaibah](https://github.com/AnasGharaibah)): speech to text, TTS, dialect, record page
- **Faris** ([@Faris25-dev](https://github.com/Faris25-dev)): backend API, confirm gate, family approval, WhatsApp stretch

# Jibli: Team Brief for Careem Builders '26

Updated Sat 21 Nov 2026. This replaces the original brief.

**Deck:** https://claude.ai/artifact/Pc7w5HzvK1eDssBcyeustV · **Mockups:** https://claude.ai/artifact/6tedq3bC2pBFxiMtgUifgh · **Anas's research:** https://claude.ai/artifact/RwiHoG3oN8bGeBzeqmTrvH

## The idea

**Jibli (جيبلي, "bring me")** is voice ordering on Careem for everyone who would rather talk than tap: busy parents, drivers, people with weak eyesight, and elders who can't order alone (one key group, not the only one).

1. You send a voice note in Jordanian Arabic: «ابعتلي خبز وحليب وبيض».
2. The agent builds a real Careem grocery cart through Careem MCP.
3. It reads back the items, total and address by voice.
4. Nothing is bought until you, or a family member who approves and pays, say yes.
5. **It learns you, like Duolingo:** it remembers your usual items ("زي كل مرة"), and next it will remind you before you run out and offer a cheaper deal only when it helps.

**In the demo:** steps 1–4 plus memory. **Pitched as next, not demoed:** reminders, deal-finding (bandit + uplift), WhatsApp, Food/Box, and Rides (Careem lists Rides as "coming soon").

**Honesty rules:** never add items without asking · no fake urgency · one suggestion per order · back off when ignored · "what do you know about me?" + delete.

## Judging (100 points)

| Criterion | Points | How we score |
|---|---|---|
| Technical execution & integration (Bedrock, Kiro, Careem MCP) | 30 | Name each on the architecture slide; real MCP calls live; Kiro specs in the repo |
| Innovation | 25 | Dialect voice ordering + a learning loop that nudges first |
| Impact / Super App scale | 25 | New direct customers, more weekly orders, cheaper promos, metrics |
| UX | 10 | One button, spoken read-back, family approval |
| Pitch | 10 | 3 min on time, live demo, ready for judge Q&A |

## Schedule: Sun 22 Nov, The ARC, Amman

| Time | What |
|---|---|
| 8:30 | Check-in. **Bring an official ID.** |
| 9:15 | Careem MCP training |
| 10:15–18:00 | Build sprint |
| 18:00 | Demos: 3 min live demo + 2 min Q&A (at least one judge question) |
| 20:15 | Awards |

Free Careem Rides code to get there arrives Saturday evening (from Tareq Khalaf).

## Stack

| Part | Choice |
|---|---|
| Voice in | **Web record button (guaranteed demo).** Stretch: WhatsApp via Twilio sandbox or a Meta test number. No Telegram: it is blocked in Jordan. |
| Speech to text | Whisper or Cohere Transcribe Arabic, whichever wins tonight's test |
| Agent | Claude on Amazon Bedrock, on AgentCore Runtime |
| Memory | AgentCore Memory (Mem0 was considered; it's background research only) |
| Ordering | Careem MCP: `search_groceries_get_top_user_items` → `search_groceries_items` → `create_grocery_cart_with_quantities` → `cart_get_basket_price` → **confirm gate** → `cart_grocery_checkout` |
| Voice out | TTS, Anas picks tonight |
| Build | Kiro, spec-first (requirements, design, tasks) |

Careem playbook rules: always pass lat/lng (`user_info` for saved addresses), confirm before spending, never blindly retry checkout or cart changes, and expect around 6 chained tool calls.

## Roles

- **Hashim:** Bedrock + AgentCore agent, Careem MCP connection, AWS setup, Kiro specs. Pitch: cover, problem, architecture, close.
- **Anas:** speech to text, TTS, dialect handling, record button page. Pitch: solution, "it learns you", drives the demo laptop.
- **Faris:** backend API, confirm gate (checkout only after a human yes), family approval page, WhatsApp stretch, demo stability. Pitch: impact; holds the approval phone.

## Tonight (Sat 21 Nov)

First check the T&Cs (builders.careem.com/hackathon/terms) on whether code can be written before the day. If not, do only setup, tests and specs.

- [ ] **Anas:** record about 10 Jordanian voice notes from different people; compare Whisper and Cohere Transcribe Arabic; report "__ of 10 understood". Pick a TTS voice. Record a clean fallback voice note.
- [ ] **Hashim:** enable Claude on Bedrock in our AWS account, deploy an AgentCore Runtime hello-world, read the Careem MCP docs (getting-started, journeys, agent-playbook, sandbox), draft the Kiro spec.
- [ ] **Faris:** plan the backend and confirm-gate design; test the Twilio WhatsApp sandbox or Meta test number.
- [ ] **All:** read the deck and speaker notes, learn your lines, charge laptops and phones, bring ID and a hotspot.

## Sunday, hour by hour

| Time | Goal | Done when |
|---|---|---|
| 10:15–11:15 | MCP auth working; one grocery journey from code. STT on the record page. Backend skeleton. | Basket price returned from code |
| 11:15–13:00 | Agent: text in → cart → basket price. Wire record button → STT → agent → TTS. | Spoken read-back from a live voice note |
| 13:00–14:30 | Confirm gate + family approval page. AgentCore Memory for "زي كل مرة". | Approve on phone → checkout (or stop at basket price) |
| 14:30–16:00 | Polish UI to match the mockups. Stretch: a simple reminder (from order history) or WhatsApp. **Only if the core flow is solid.** | |
| 16:00 | **Feature freeze.** Record a backup screen recording of the full flow. | Video saved offline |
| 16:00–17:30 | Rehearse the 3-min pitch at least 3 times; fill bracketed items in the speaker notes (dialect score, gate in backend, audio deletion, Kiro line, real checkout?) | Under 3:00 every time |
| 17:30–18:00 | Buffer, charge everything, test the venue Wi-Fi and microphone | |

## Demo script (3:00)

| Time | Who | What |
|---|---|---|
| 0:00 | Hashim | Cover and problem: "Ordering still means taps and menus. Everyone already sends voice notes." |
| 0:20 | Anas | Solution in 4 screens, then "it learns you" (reminders shown as next) |
| 0:40 | Anas (laptop), Faris (phone) | Live: say «ابعتلي خبز وحليب وبيض» → spoken read-back → point at the memory item → «آه» → Faris approves → "on its way" |
| 2:00 | Anas | Flash the WhatsApp mockup as next |
| 2:10 | Hashim | Architecture: Whisper/Cohere → Claude on Bedrock + AgentCore → Careem MCP, confirm gate, Kiro |
| 2:30 | Faris | Impact: who it serves, what Careem gains, what we measure |
| 2:45 | Hashim | Team, then close: «احكي، وإحنا بنجيبلك» |

**Fallbacks:** loud room → play the recorded voice note; network or MCP down → play the screen recording and say so. Agree with organisers beforehand whether checkout is real; if not, stop at the basket price.

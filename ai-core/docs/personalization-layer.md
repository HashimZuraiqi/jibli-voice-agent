# Jibli — Personalization Layer

Nov 22, 2026 · Anas Gharaibah · live version with diagram: https://claude.ai/artifact/PsZiqbtB16AXmknAXmyBX4

## How it works

The personalization layer decides **what** Jibli suggests to each user and **when**, so the AI only has to say it well: which groceries are running out, the usual ride or Box delivery, how to word the reminder, and whether an offer is worth giving. It is plain Python with classic models; the AI never computes these numbers.

The loop: **predict** (groceries running out, usual ride and Box) → **decide** (reminder style with a LinUCB bandit, offer with an uplift model) → **guardrails** (quiet hours, caps, a yes before paying) → **speak** (advice to the AI, voice note in Arabic) → **learn** (yes / no / silence becomes the bandit's reward; lasting facts go to memory) → next time.

The guardrails sit between deciding and speaking, so nothing reaches the user or spends money without passing them, and every reply flows back to make the next suggestion better.

## Where the code is

The layer is plain Python in `ai-core/agent/personalization/`; memory sits next to it in `agent/memory.py`.

| File | Job | Main functions |
| --- | --- | --- |
| `layer.py` | Joins every part into one piece of advice for the brain; decides when to remind; turns replies into learning | `advise`, `reminder`, `record_reminder`, `feedback`, `snapshot` |
| `repurchase.py` | Predicts which groceries are running out | `predictions`, `due_items`, `similar_user_staples` |
| `services.py` | Predicts the usual ride at this time and the usual Careem Box delivery | `usual_ride`, `usual_box` |
| `bandit.py` | Picks the reminder style and learns from replies (LinUCB, MABWiser) | `ReminderBandit.choose`, `update`, `context_vector` |
| `uplift.py` | Decides whether an offer is worth giving (T-learner, CausalML) | `OfferModel.uplift`, `features` |
| `guardrails.py` | Safety rules checked before anything is said or done; the fast yes / no word check | `can_remind`, `can_offer`, `can_place_order`, `says_yes`, `says_no`, `safe_to_remember` |
| `agent/consent.py` | Decides what the user's reply **means** for the waiting order: yes, no or unclear | `judge` |
| `agent/memory.py` | What the agent remembers about each user (Mem0 or AgentCore Memory) | `recall`, `learn`, `all`, `forget` |

## Predict groceries: what is running out

`repurchase.py` learns each user's own rhythm per item, the "Buy It Again" idea Instacart and Target use, and calls an item running out when its due score reaches **0.9**.

1. For every item the user has bought, list the purchase dates from the order history.
2. **Gap** = the median number of days between purchases (needs 3 or more purchases). With fewer, use the catalog's `default_gap_days` for that kind of item (bread 2 days, rice 21, olive oil 35).
3. **Due score** = days since the last purchase ÷ gap. 1.0 means "exactly when they usually rebuy".
4. Items with a score of 0.9 or more are "running out"; the usual quantity is the amount bought most often.
5. **New users** (fewer than 3 orders) have no rhythm yet, so the layer suggests the 5 items other users buy most (cold start).

Example: Um Khaled buys milk about every 3.5 days; 7 days after her last carton the score is 2.0, so milk is running out.

## Predict rides and Box deliveries

`services.py` reads the ride and Box history in `data/services.json` and finds habits tied to the time of the week (rides) or to a repeating gap (Box).

| | Usual ride (`usual_ride`) | Usual Box delivery (`usual_box`) |
| --- | --- | --- |
| Looks at | Past rides on **the same weekday** within **1.5 hours** of now | All the user's Box deliveries |
| Counts as a habit when | The same trip (from, to, product) happened **3+ times** | Always the most repeated trip (from, to, vehicle, category) |
| "Due" when | It is the right weekday and hour | Days since the last one ≥ 0.9 × the median gap |
| Gives the brain | from, to, product (Go, Comfort, Business), times seen, place ids and coordinates | from, to, vehicle (motorbike, car, van), category, days since, gap, due |
| Example: Um Khaled (68) | Tuesday 09:10: Home → Dubai Mall by Comfort, seen 10 times | Home → Work by car, about every 28 days, 41 days ago: due |
| Example: Lina (22, new demo customer) | Weekday 08:00: Home → Work by Go; Mon and Wed 17:00: Work → Gym; Thursday 21:00: Home → Dubai Mall by Comfort; Saturday: none | No Box habit |

Places are the saved places of the Careem account (Home, Work, Gym, Dubai Mall, Airport T3), so the brain can quote and book them directly.

## Decide the reminder style

`bandit.py` uses a contextual bandit (LinUCB, the method Yahoo and Netflix use, through the MABWiser library) to pick how a reminder is worded for this person at this moment, and it gets better with every reply.

| Style | How the voice note sounds |
| --- | --- |
| gentle | Warm, asks how they are first, then mentions the items |
| practical | Straight to the point: the items running out and "shall I order?" |
| family | Mentions the family member who pays, e.g. "shall I send it to Khaled to confirm?" |
| short | One short sentence, easy to answer yes or no |

- **Context** (5 numbers, each scaled 0 to 1): hour of day, age, how many items are due, days since the last order, Arabic speaker or not.
- **Choice:** the style with the highest expected reply rate for this context (`predict_expectations`).
- **Learning:** the reply to the reminder is the reward: **yes = 1**, **no or silence = 0**, applied with `partial_fit` and saved to `state/bandit.pkl`.
- **Cold start:** before any real replies, the bandit is trained on 3,000 logged replies from similar users (synthetic for the demo), so a new user starts from what works for people like them.

## Decide offers

`uplift.py` gives a discount only to people it would actually change, the approach DoorDash, Uber and Booking use, so promotions are not wasted on people who would order anyway.

- **Model:** a CausalML T-learner (two gradient-boosting models: one for people who got an offer, one for people who did not), trained on 20,000 synthetic campaign rows.
- **Features:** orders per month, average basket, price sensitivity, days since the last order.
- **Uplift** = predicted chance of ordering with the offer − without it.
- **Rule:** offer only if uplift ≥ **0.05** and no offer was given in the last **7 days**. The offer is **15% off, up to 1.5 JOD**.

| User | Orders a month | Uplift | Offer? |
| --- | --- | --- | --- |
| Um Khaled | 25 | about 0 | No: she orders anyway |
| Abu Sami | 24 | about 0 | No |
| Hajjeh Fatima (new) | 0 | 0.21 | Yes: it is likely to bring her first order |

## Guardrails

`guardrails.py` is checked before anything is said or done; every check is written to the log on the demo page, and every rule fails closed (when in doubt, it says no).

| Rule | What happens |
| --- | --- |
| No reminders 22:00–08:00, at most 1 per day | The reminder is blocked and the reason is shown |
| At most 1 offer per 7 days | The offer is withheld even if the uplift is high |
| Nothing is paid without a confirmation request first | Jibli says the price and asks; the order waits for an answer |
| The user herself is asked by default | The family member who pays is asked only when she wants that or the spend cap requires it; whoever answers first decides. The person an order is sent to (e.g. food sent to Khaled) is not the one who confirms it |
| The user's yes is judged by meaning (next section) | Any kind of yes places the order; unclear → ask once more; a clear no → the waiting order is cancelled |
| The yes must be recent | Within her next 2 messages and 30 minutes of the question; later, Jibli asks again |
| Spend cap per order: 30 JOD or 150 AED | Above it, the family member must approve; the price always comes from Careem's own quote or basket, never from the AI |
| Unknown currency or a price that is not a real number | Refused |
| Real Careem server | `CAREEM_ALLOW_CHECKOUT` is off by default: Jibli builds the real cart and price but never pays; the ride stand-in is switched off; addresses come from the user's own Careem account. The local sandbox places its pretend orders |
| No sensitive data in memory | ID and card numbers, passwords and health words are never stored |

## How Jibli knows the user said yes

`agent/consent.py` reads the user's reply together with the order that is waiting, so any sentence that **means** yes places it, in Jordanian Arabic, other dialects, formal Arabic, English or Arabizi (Arabic in Latin letters).

1. **Clear yes words count at once**, with no AI call: اه، اكيد، تمام، كمّل، اعتمد، توكل، اطلبه، yes, sure, go ahead, aywa, akeed, 5alas, and "no problem" phrases (ما في مشكلة، ما عندي مانع; ليش لا / why not as the whole reply).
2. **Anything else is read by Claude**, which answers YES, NO or UNCLEAR. The order summary and the reply are passed to it as quoted data, never as instructions.
3. **Yes** → the code places the order itself through every guardrail, and the AI only tells her how it went. **Unclear** → Jibli asks once: "بدك أكمّل الطلب؟". **No** → the waiting order is cancelled.

| Reply | Decision |
| --- | --- |
| اه اكيد كمل الطلب، على بركة الله، روح جيبلي ياه، حسناً أكمل الطلب، I'm in go for it، aywa yalla | Yes: order placed |
| خلص مش لازم، لا بطلت، cancel it please، la2 msh hala2 | No: order cancelled |
| طيب بشوف، ماشي بس بعدين، maybe later، اه بس غير الوقت، قديش السعر؟ | Unclear: asks again |

Safety: a question is never a yes. A reply with a no or wait word (لا، مش، بعدين، cancel…), a condition (بس، غير، شيل، but, change…) or a question word (شو، كم، how…) can never become a yes, even if the AI reads it that way. If the AI cannot be reached, Jibli asks again instead of guessing. In a live test Claude judged 26 of 26 replies correctly.

## Memory

`agent/memory.py` remembers lasting facts each user tells the agent, using Mem0 (local) or Amazon Bedrock AgentCore Memory (`MEMORY_PROVIDER`), and gives the brain the 5 facts closest to each new message.

- **Stored:** lasting preferences and household facts, e.g. "her husband takes no sugar: buy the sweetener", "prefers the small Arabic bread", "her son Khaled pays and confirms". Facts are pulled out of the message by an LLM (Claude Haiku on Bedrock).
- **Never stored:** one-off orders, confirmations, instructions to the agent ("order without asking"), and sensitive details (ID or card numbers, passwords, health words).
- **Search works across languages:** asking about "sugar" finds "بدون سكر" (multilingual embeddings, FastEmbed).
- **The user stays in control:** "شو بتعرف عني؟" lists everything remembered, and any fact (or all of them) can be deleted by voice or with the × on the demo page.
- **Seed facts** the family gives at sign-up are stored without an LLM call.

## What the brain receives

On every message `layer.advise(user, now)` returns one piece of advice that goes into the AI's instructions; the AI words it, but never changes the numbers.

| Field | Meaning | Um Khaled, Tuesday 09:10 |
| --- | --- | --- |
| `running_out` | Groceries due now, with usual quantity | Milk, tea, small bread |
| `cold_start`, `suggestions_for_new_user` | New user? What similar users buy | No |
| `usual_ride` | The habitual ride at this time | Home → Dubai Mall, Comfort |
| `usual_box` | The repeated Box delivery and whether it is due | Home → Work by car, due |
| `style`, `style_scores` | Reminder style chosen by the bandit, with every style's score | family |
| `offer`, `offer_decision` | The discount (or none) and why | None: uplift about 0 |

**When a reminder is sent:** `layer.reminder` checks the guardrails and fires only if groceries are running out, a Box delivery is due, or a usual ride is near. The AI writes the voice note in the chosen style; `record_reminder` logs it only once it was actually written. The user's next yes, no or silence goes back through `feedback` to teach the bandit.

## Tests, limits and next steps

**Tests.** `.venv/bin/python -m pytest -q` runs 100 tests without any AI: running-out items, cold start, offers only where they change behavior, the bandit learning from replies, reminder and offer limits, the confirmation rules, the spend cap, the yes / no / unclear decision (with a fake AI for the meaning part), the sensitive-data filter, the usual ride and Box predictions, and the real-Careem switches (no paying, no ride stand-in).

**Limits.**

- The bandit and the offer model learn from synthetic data for the demo; their numbers show the method, not real behavior.
- The same reminder style can repeat day after day; people tune that out.
- Ride and Box habits are simple counts on the history; there is no seasonality yet.
- Reading the meaning of a yes costs one AI call (about 1 second) when the reply has no clear yes word; if the AI is down, only clear yes words work.
- Rides are a local stand-in until Careem adds rides to its sandbox, so they are switched off on the real Careem account.

**Next steps:**

- [ ] Replace synthetic logs with real replies and test the bandit offline first (Li et al., Yahoo).
- [ ] Add Duolingo's recency penalty so the same style is not used too often.
- [ ] Add a budget optimizer for offers, as DoorDash does.
- [ ] Add brand loyalty and "bought in the last 5 orders" to the running-out prediction (Instacart).

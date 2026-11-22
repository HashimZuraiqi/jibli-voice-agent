# Jibli — Personalization Models in Graphs

Nov 22, 2026 · Anas Gharaibah

**The charts and diagrams live in the online version:** https://claude.ai/artifact/WQUBUq949Kn4KrB9rK6HEB
This file keeps the explanations and the numbers behind each chart. Full text of the layer: [personalization-layer.md](personalization-layer.md).

## 1. Repurchase: what is running out

**Not a trained model, a simple rule on each user's own rhythm** (the "Buy It Again" idea Instacart and Target use): if Um Khaled buys milk every 3.5 days, then 7 days after her last carton milk is twice overdue.

*Diagram:* purchase dates → usual gap (median days between buys: 3.5) → due score (days since last buy ÷ gap = 7 ÷ 3.5 = 2.0) → running out if 0.9 or more.

*Chart — "Milk is running out: 2 times its usual gap since the last carton":* Um Khaled's milk due score each day from 27 Oct to 24 Nov 2026. The line climbs a little every day since her last purchase and falls back to 0 the day she buys milk. Every time it crossed the dashed 0.9 line, she bought milk within a day or two, which is why 0.9 is the trigger. On 24 Nov it is at 2.0, so milk goes into her reminder. The usual gap is the *median* of the gaps between her purchases, so one unusual week does not move it.

## 2. Rides and Box: the usual trip

**Also counting, not a trained model.** A ride is a habit when the same trip happened on the same weekday at about the same time at least 3 times; a Box delivery is due when it has been longer than usual since the last one.

*Chart — "On Tuesdays around 9 she always takes the same ride":* Um Khaled's Tuesday rides by hour over 10 weeks: 10 rides at 9:00 (Home → Dubai Mall) and 10 at 12:00 (Dubai Mall → Home). At Tuesday 09:10 the model looks only at 07:40–10:40, so her usual ride now is Home → Dubai Mall by Comfort; the noon ride home is suggested only around noon.

*Chart — "Her monthly Box delivery is overdue: 41 days since the last, usual gap 28":* deliveries Home → Work by car on 14 Sep and 13 Oct. From 0.9 × 28 ≈ 25 days after the last one (7 Nov) the delivery counts as due; on 24 Nov it is day 41, so the reminder offers it again.

## 3. Bandit: how the reminder is worded

**A real machine-learning model that learns online** (LinUCB, the method Yahoo used for news and Netflix for artwork). For every reminder it guesses which of 4 styles this person is most likely to answer "yes" to at this moment, sends that one, and updates itself from the reply (yes = 1, no or silence = 0).

*Chart — "The bandit picks the family style for all three, by very different margins"* (expected chance of a yes):

| User | gentle | practical | family | short |
| --- | --- | --- | --- | --- |
| Um Khaled, Tue 09:10 | 42% | 34% | **45%** | 26% |
| Abu Sami, Fri 17:00 | 41% | 42% | **43%** | 38% |
| Hajjeh Fatima, Sun 10:00 | 32% | 17% | **33%** | 18% |

For Um Khaled the family style leads clearly; for Abu Sami three styles are almost tied, so a few replies could change his style; for Hajjeh Fatima, who is new, every score is lower because the model knows less.

*Chart — "It takes 18 'no' replies in a row to switch her from family to gentle":* each "no" lowers the family score a little (45.4% → 41.8%), but the model started from 3,000 similar users' replies, so gentle (41.9%) only wins after 18 "no" replies in a row. A lighter prior, or Duolingo's trick of penalizing a recently used style, would make it switch sooner.

## 4. Uplift: who gets an offer

**A causal machine-learning model** (the approach DoorDash, Uber and Booking use). It asks "will an offer **change** whether this person orders?", so discounts are not spent on people who would buy anyway.

*Diagram:* the user's features → Model A (chance to order WITH an offer) and Model B (WITHOUT) → uplift = A − B → offer 15% off (up to 1.5 JOD) only if uplift ≥ 0.05 and no offer this week.

*Chart — "Only the new user gets an offer: it raises her chance to order by 21 points":*

| User | Without offer | With offer | Uplift | Decision |
| --- | --- | --- | --- | --- |
| Um Khaled (25 orders a month) | 56% | 52% | −4 pts | no offer |
| Abu Sami (24 orders a month) | 45% | 49% | +4 pts | no offer |
| Hajjeh Fatima (new) | 18% | 39% | +21 pts | offer |

*Chart — "An offer pays off only for people who order less than about 5 times a month":* keeping everything else fixed (basket 10, price-sensitive 0.7, 10 days since the last order), the uplift is +28 points at 0 orders a month, +7 at 4, and below the 5-point line from about 5 orders a month on.

## How the numbers were made

Every chart was computed by running Jibli's own code on its demo data on 22 Nov 2026, with "now" set to Tuesday 24 Nov 2026 at 09:10; nothing was typed by hand.

| Chart | Code | Data |
| --- | --- | --- |
| Milk due score | `repurchase.item_history` + the median-gap rule, day by day | `data/orders.json` (120 days of invented orders) |
| Tuesday rides, Box deliveries | `services.usual_ride`, `services.usual_box` | `data/services.json` (40 rides, 7 Box deliveries) |
| Style scores, learning curve | `ReminderBandit.choose`, then `update(…, "no")` 18 times on a copy | Bandit prior from `data/bandit_logs.json` (3,000 synthetic replies) |
| Uplift per user, uplift by frequency | `OfferModel.model.predict(…, return_components=True)` | Model trained on `data/uplift_logs.json` (20,000 synthetic rows) |

All data is invented for the demo, so the charts show **how each model behaves**, not facts about real Careem users.

# Jibli pitch: WhatsApp messages

Copy each block into WhatsApp. `*bold*` and `_italic_` show as WhatsApp formatting.

## 1. Anas's lines

```
*Jibli pitch: Anas's lines* 🎤
3 slides + the video. Total about 1:15.

*Slide 3 · Video (0:30–1:05)*
"Here's Um Khaled with Jibli."
▶️ Play the video, then only short lines:
• «ابعتلي خبز وحليب وبيض» → "She just talks."
• Read-back → "Small bread: she told Jibli once, and it remembered."
• «اه اكيد كمّل الطلب» → "That means yes."
• Khaled taps Approve → "Khaled gets one tap, not a phone call."
After: "Nothing is paid until a human says yes."

*Slide 4 · «جيبلي» (1:05–1:15)*
"This is Jibli, جيبلي, _bring me_. You talk, Jibli orders on Careem, and it learns you."
*«جيبلي، وانت خليك مرتاح»*

*Slide 7 · Jibli learns you (1:40–2:00)*
"Jibli learns you from what you already do.
*What you buy:* her milk runs out every 3.5 days, so Jibli reminds her before it does.
*Where you go:* that's how it knew Faris goes to the gym every Monday.
*How you answer:* every yes or no teaches it how to talk to you.
And you can always ask «شو بتعرف عني؟» and delete anything."

*Slide 8 · Why it matters (2:00–2:15)*
"For the user: reminded before you run out, your usual ride with no typing, and nothing ordered without your yes.
For Careem: more repeat orders, discounts only where they change a decision, and it gets better with every reply."
```

## 2. Hashim's lines

```
*Jibli pitch: Hashim's lines* 🎤
5 slides. Total about 1:05.

*Slide 2 · Um Khaled (0:15–0:30)*, right after Faris's phone call
"That was Jibli. Now meet Um Khaled. She's 68 and lives in Amman.
Every few days, the bread runs out. She can't read the menus in the app, so she calls her son Khaled.
He's in a meeting. She calls again. And again."

*Slide 5 · Two generations (1:15–1:25)*
"Um Khaled and Faris: two generations, one problem. Menus and taps.
But both of them already send voice notes every day."

*Slide 6 · How we found it (1:25–1:40)*
"We asked families how their parents order.
We studied how DoorDash, Instacart, Uber and Duolingo learn their users.
And for the voice we use OpenAI's Whisper: only 16% word error on Arabic.
Nobody built one you just talk to."
_If a judge asks:_ 16% = Whisper large-v2 on OpenAI's Arabic test (FLEURS, Whisper paper Table 13). It's formal read Arabic, not Jordanian voice notes.

*Slide 9 · How it's built (2:15–2:30)*
"Your voice goes to Whisper. Claude on Amazon Bedrock is the brain. Careem MCP builds the real cart.
And nothing is paid until a human says yes. Prices come only from Careem, never from the AI.
We built it spec-first in Kiro."

*Slide 11 · Close (2:45–2:58)*, one click per line
"Faris didn't type.
Um Khaled didn't call.
They just talked.
*«جيبلي، وانت خليك مرتاح»*"
```

## 3. The models behind "Jibli learns you" (for judge Q&A)

```
*🧠 How Jibli learns you: the models*
For judge questions. Short answer first, details after.

*1. Claude Sonnet 5.5 on Amazon Bedrock: the brain*
Understands Jordanian Arabic, English and Arabizi, and builds the real cart with Careem MCP tools. It never gets the "pay" tool: the code places the order only after a human yes.

*2. Whisper large-v2 (OpenAI): speech to text*
Turns the voice note into text. 16% word error on Arabic (OpenAI's FLEURS test).

*3. Memory: Mem0 (or Amazon AgentCore Memory)*
Remembers lasting facts: "no sugar for my husband", "small bread". Claude Haiku pulls the fact out of the message, and multilingual search means "sugar" finds «سكر».
Never stores ID numbers, cards, passwords or health details. «شو بتعرف عني؟» shows everything and you can delete any of it.

*4. Repurchase rhythm: what's running out*
Not a trained model, a rule per person and item (the "Buy it again" idea from Instacart and Target).
Gap = median days between buys. Due score = days since last buy ÷ gap. At 0.9 or more it's running out.
Example: milk every 3.5 days, 7 days since the last one → score 2.0 → remind.
New user → suggests what similar users buy most (cold start).

*5. Usual ride and Box: habits*
Counts on the history. A ride is a habit when the same trip happened on the same weekday within 1.5 hours, 3+ times (Faris: gym every Monday). A Box delivery is due at 0.9 × its usual gap.

*6. LinUCB contextual bandit: how to talk to you* (real ML, learns live)
Picks 1 of 4 reminder styles: gentle, practical, family, short.
Context: hour, age, items due, days since last order, language.
Reward: yes = 1, no or silence = 0, and it updates after every reply.
Same method as Yahoo news and Netflix artwork. Library: MABWiser.

*7. Uplift model, T-learner: who gets a discount* (causal ML)
Two gradient-boosting models: chance to order *with* an offer vs *without*. Uplift = the difference.
Offer (15%, max 1.5 JOD) only if it raises the chance by 5+ points, and max 1 offer a week.
Example: the new user +21 points → offer; Um Khaled orders anyway → no offer.
Same idea as DoorDash, Uber and Booking. Library: CausalML.

*8. Consent judge: did she say yes?*
Clear yes words count at once; anything else, Claude reads the meaning → YES / NO / UNCLEAR. Unclear → asks once more.
A question, a "no", a "but…" or a "later" can never become a yes.
Live test: 26 out of 26 replies judged right.

*9. Guardrails*
No reminders 22:00–08:00, max 1 reminder a day, max 1 offer a week, spend cap 30 JOD, every price from Careem.

*📚 The 4 apps we studied, and what we took from each*
• *Instacart:* "Buy It Again" predicts what you'll rebuy and when → our *repurchase rhythm* (milk every 3.5 days).
• *Duolingo:* a bandit picks the wording of its practice reminders and learns from who comes back, and it avoids repeating the same message → our *LinUCB bandit* for reminder style.
• *Uber:* built CausalML, the open-source uplift library we use, to send promotions only where they change what people do → our *uplift model*.
• *DoorDash:* uplift models plus a promo budget optimizer, so discounts go to customers they actually bring back → our "discount only if +5 points" rule (the budget optimizer is our next step).

_Be honest if asked:_ the bandit and the uplift model are trained on synthetic demo data for now (3,000 and 20,000 rows). The numbers show the method; real user replies would replace them.
```

## 4. The whole speech in Arabic (one paragraph)

```
«مسا الخير فارس، خلص دوامك؟ بدك أطلبلك Go من الشغل عالجيم، زي كل اثنين؟» «اه يلا» «تمام، السيارة جاية بعد ٤ دقايق.»

هاد كان جيبلي. هلّق خلّونا نعرّفكم على أم خالد، عمرها ٦٨ سنة وساكنة بعمّان. كل كم يوم بيخلص الخبز، وهي ما بتعرف تقرأ القوائم الصغيرة بالتطبيق، فبتتصل بابنها خالد. خالد باجتماع، بتستنّى، بترجع بتتصل، ومرة كمان.

هيك صارت أم خالد مع جيبلي: بتحكي بس «ابعتلي خبز وحليب وبيض»، وجيبلي بيقرألها السلة الحقيقية من كريم، ولاحظوا إنه اختار الخبز الصغير، لأنها حكتله مرة إنها ما بتحب الكبير وهو تذكّر. بترد عليه «اه اكيد كمّل الطلب»، وجيبلي بيفهم إنها يعني نعم، وخالد بدل ما يجيه تلفون بتجيه كبسة وحدة للموافقة، وما بندفع ولا قرش قبل ما إنسان يحكي نعم.

هاد جيبلي: إنت بتحكي، جيبلي بيطلب من كريم، وبيتعلّم عليك. جيبلي، وانت خليك مرتاح.

أم خالد وفارس جيلين مختلفين بس عندهم نفس المشكلة: قوائم وكبسات، والاثنين أصلًا بيبعتوا فويسات كل يوم.

سألنا عائلات كيف أهاليهم بيطلبوا، ودرسنا كيف دور داش وإنستاكارت وأوبر ودولينجو بيتعلّموا على مستخدمينهم، وللصوت بنستخدم Whisper من OpenAI، ونسبة الخطأ فيه بالعربي بس ١٦٪. ما حدا عمل تطبيق بتحكي معه وبس.

جيبلي بيتعلّم عليك من إشي إنت أصلًا بتعمله: شو بتشتري، فالحليب عند أم خالد بيخلص كل ثلاث أيام ونص، فبيذكّرها قبل ما يخلص؛ وين بتروح، وهيك عرف إنه فارس بيروح عالجيم كل اثنين؛ وكيف بترد، فكل نعم أو لا بتعلّمه كيف يحكي معك. وبأي وقت بتقدر تسأله «شو بتعرف عني؟» وتمسح أي إشي.

للمستخدم: بيذكّرك قبل ما يخلص الإشي، مشوارك المعتاد بدون ما تكتب، وما بيطلب إشي بدون موافقتك. ولكريم: طلبات متكررة أكثر، خصومات بس للي فعلًا بتفرق معه، وكل رد بيخلّيه أذكى.

كيف بنيناه: صوتك بيروح على Whisper، وClaude على Amazon Bedrock هو العقل، وCareem MCP بيبني السلة الحقيقية، وما في دفع قبل ما إنسان يوافق، والأسعار دايمًا من كريم مش من الذكاء الاصطناعي، وبنيناه spec-first على Kiro.

وليش كريم بتربح؟ زباين جداد، أهالي صاروا يطلبوا لحالهم؛ طلبات أكثر، «خلص عندي» بتصير طلب من كريم بدل مشوار عالدكان؛ وخصومات أذكى، بس وين بتجيب زبون فعلًا.

فارس ما كتب ولا حرف، وأم خالد ما اتصلت، هم بس حكوا. جيبلي، وانت خليك مرتاح.
```

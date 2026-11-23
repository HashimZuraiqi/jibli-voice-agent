# Jibli — Pitch Script (3:00)

Careem Builders '26 · Story-telling pitch · Hashim, Anas, Faris
**Slides:** https://claude.ai/artifact/Ws8Tt82VfEnAirpw7FZcjd · **Slogan:** «جيبلي، وانت خليك مرتاح»

> Slides show only a title and up to 3 short items. Everything below is what we **say**.

---

## At a glance

| # | Time | Who | Slide on screen |
|---|---|---|---|
| 1 | 0:00–0:15 | Faris | Dark screen: the phone rings, live |
| 2 | 0:15–0:30 | Hashim | Um Khaled: "Every order is a phone call." |
| 3 | 0:30–1:05 | Anas | Video: "She just talks." (30 sec) |
| 4 | 1:05–1:15 | Anas | «جيبلي» + slogan |
| 5 | 1:15–1:25 | Hashim | "Two generations. One problem." |
| 6 | 1:25–1:40 | Hashim | "How we found it" |
| 7 | 1:40–2:00 | Anas | "Jibli learns you" |
| 8 | 2:00–2:15 | Anas | "Why it matters" |
| 9 | 2:15–2:30 | Hashim | "How it's built" |
| 10 | 2:30–2:45 | Faris | "Why Careem wins" |
| 11 | 2:45–2:58 | Hashim | Close: «جيبلي، وانت خليك مرتاح» |

---

## 1. The phone rings, live — 0:00–0:15 · Faris

**Slide:** dark screen.

*(The team stands quietly. Faris's phone buzzes. He holds it to the mic.)*

> **Jibli:** «مسا الخير فارس، خلص دوامك؟ بدك أطلبلك Go من الشغل عالجيم، زي كل اثنين؟»
> **Faris:** «اه يلا»
> **Jibli:** «تمام، السيارة جاية بعد ٤ دقايق.»

## 2. Um Khaled — 0:15–0:30 · Hashim

**Slide:** "Every order is a phone call." + 3 missed calls to Khaled.

> That was Jibli. Now meet Um Khaled. She's 68 and lives in Amman.
> Every few days, the bread runs out. She can't read the menus in the app, so she calls her son Khaled.
> He's in a meeting. She calls again. And again.

## 3. The video — 0:30–1:05 · Anas

**Slide:** "She just talks." + the 30-second video.

> Here's Um Khaled with Jibli.

*(Play the video. Only short lines while it plays.)*

| In the video | Anas says |
|---|---|
| She says «ابعتلي خبز وحليب وبيض» | "She just talks." |
| Jibli reads back the cart, with small bread | "Small bread: she told Jibli once, and it remembered." |
| She says «اه اكيد كمّل الطلب» | "That means yes." |
| Khaled taps Approve | "Khaled gets one tap, not a phone call." |

> Nothing is paid until a human says yes.

## 4. Meet Jibli — 1:05–1:15 · Anas

**Slide:** «جيبلي» · «جيبلي، وانت خليك مرتاح» · Talk · Order · Learns you.

> This is Jibli, جيبلي, "bring me." You talk, Jibli orders on Careem, and it learns you.
> **«جيبلي، وانت خليك مرتاح».**

## 5. Two generations, one problem — 1:15–1:25 · Hashim

**Slide:** Um Khaled "Can't read the menus" · Faris "Same taps, every day" · "Both already send voice notes."

> Um Khaled and Faris: two generations, one problem. Menus and taps.
> But both of them already send voice notes every day.

## 6. How we found it — 1:25–1:40 · Hashim

**Slide:** Asked families · Whisper: 16% Arabic word error · 4 apps studied.

> We asked families how their parents order.
> We studied how DoorDash, Instacart, Uber and Duolingo learn their users.
> And for the voice we use OpenAI's Whisper: only 16% word error on Arabic.
> Nobody built one you just talk to.

**If a judge asks about the 16%:** Whisper paper (OpenAI, 2022), Table 13, Whisper large-v2 on FLEURS Arabic. FLEURS is read formal Arabic, not Jordanian voice notes, so say "on OpenAI's Arabic test". Keep "we asked families" only if we really did.

## 7. Jibli learns you — 1:40–2:00 · Anas

**Slide:** Milk every 3.5 days · Gym every Monday · Your style, learned · «شو بتعرف عني؟» See it. Delete it.

> Jibli learns you from what you already do.
> **What you buy:** her milk runs out every 3.5 days, so Jibli reminds her before it does.
> **Where you go:** that's how it knew Faris goes to the gym every Monday.
> **How you answer:** every yes or no teaches it how to talk to you.
> And you can always ask «شو بتعرف عني؟» and delete anything.

## 8. Why it matters — 2:00–2:15 · Anas

**Slide:** For the user · For Careem, 3 points each.

> For the user: reminded before you run out, your usual ride with no typing, and nothing ordered without your yes.
> For Careem: more repeat orders, discounts only where they change a decision, and it gets better with every reply.

## 9. How it's built — 2:15–2:30 · Hashim

**Slide:** Voice → Speech to text → Claude on Bedrock → Careem MCP → Human says yes → Order.

> Your voice goes to Whisper. Claude on Amazon Bedrock is the brain. Careem MCP builds the real cart.
> And nothing is paid until a human says yes. Prices come only from Careem, never from the AI.
> We built it spec-first in Kiro.

## 10. Why Careem wins — 2:30–2:45 · Faris

**Slide:** New customers · More orders · Smarter discounts.

> New customers: parents who now order by themselves.
> More orders: "I ran out" becomes a Careem order, not a trip to the shop.
> Smarter discounts: only where they actually bring someone in.

## 11. Close — 2:45–2:58 · Hashim

**Slide:** one click per line.

> Faris didn't type.
> Um Khaled didn't call.
> They just talked.
> **«جيبلي، وانت خليك مرتاح».**

---

## Before the pitch

- [ ] Record the **30-second Um Khaled video** and put it on slide 3.
- [ ] Record Jibli's opening lines with our TTS voice and put the audio on Faris's phone.
- [ ] Send one voice note to the app on good Wi-Fi first, so Whisper large-v2 (about 3 GB) is already downloaded.
- [ ] Rehearse with a timer at least 3 times: under 3:00.
- [ ] Charge the laptop and both phones; test the mic, speakers and Wi-Fi at the venue.

---

## The whole speech in Arabic

One paragraph, no speaker names, in the order of the slides.

<div dir="rtl">

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

</div>

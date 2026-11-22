# Requirements: Jibli voice ordering

## Introduction

Jibli lets anyone order Careem groceries by sending a voice note in Jordanian Arabic. The agent builds a real
Careem cart through Careem MCP, reads back the items, total and address, and buys nothing until the user (or a
family member who approves and pays) says yes. It remembers the user's usual items ("زي كل مرة").

Demo scope (Sun 22 Nov 2026): requirements 1–6. Reminders and deals (7) are pitched as next.

## Requirement 1: Voice in

**User story:** As a user who would rather talk than tap, I want to send a voice note, so that I can order without menus.

1. WHEN the user presses the record button and stops, THE SYSTEM SHALL send the audio to speech-to-text and pass the transcript to the agent.
2. WHEN the transcript is in Jordanian Arabic, English or a mix, THE SYSTEM SHALL handle it without asking the user to switch language.
3. IF speech-to-text fails, THEN THE SYSTEM SHALL ask the user to record again and SHALL NOT guess the order.

## Requirement 2: Build the cart through Careem MCP

**User story:** As a user, I want the agent to put what I asked for in a real Careem cart, so that the order is real.

1. WHEN the user asks for items, THE SYSTEM SHALL search them with `search_groceries_items` (and `search_groceries_get_top_user_items` for "the usual") and create the cart with `create_grocery_cart_with_quantities`.
2. THE SYSTEM SHALL pass the delivery lat/lng on every Careem MCP call that takes a location (saved address from `user_info`, else the configured default).
6. THE SYSTEM SHALL offer the LLM only an allow-list of grocery and read-only Careem tools.
3. THE SYSTEM SHALL NOT add items the user did not ask for.
4. IF a Careem MCP call fails, THEN THE SYSTEM SHALL tell the user and SHALL NOT retry cart changes or checkout automatically.
5. WHERE Careem MCP is not configured (`CAREEM_PROVIDER=mock`) or cannot be reached, THE SYSTEM SHALL run the same journey on the mocked Careem data.

## Requirement 3: Read-back

**User story:** As a user, I want to hear what is in the cart, the total and the address, so that I know what I am agreeing to.

1. WHEN the cart is built, THE SYSTEM SHALL get the price with `cart_get_basket_price`.
2. WHEN the price is known, THE SYSTEM SHALL read back the items, the total and the delivery address in one short spoken sentence in the user's dialect.

## Requirement 4: Confirm gate

**User story:** As a user (or the family member who pays), I want nothing bought without a clear yes, so that no money is spent by mistake.

1. THE SYSTEM SHALL call `cart_grocery_checkout` only after a confirmation was requested and a human said yes.
2. WHEN the user confirms by voice, THE SYSTEM SHALL accept only a clear, short yes given in a later message than the request; anything unclear SHALL be asked again.
3. WHEN a family member confirms, THE SYSTEM SHALL accept it only from the family approval page, never from the LLM.
4. IF the cart changes after confirmation was requested, THEN THE SYSTEM SHALL cancel that confirmation.
5. IF the total is over the spend cap (30 JOD) or unknown, THEN THE SYSTEM SHALL require the family member's approval.
6. THE LLM SHALL NOT be able to call checkout directly; checkout arguments SHALL come from earlier Careem answers and the confirmed basket, never from the LLM.
7. IF the same basket is approved twice, THEN THE SYSTEM SHALL order it once; IF checkout fails, THEN THE SYSTEM SHALL NOT retry it for that basket.

## Requirement 5: Memory ("it learns you")

**User story:** As a returning user, I want the agent to remember my usual items and preferences, so that "زي كل مرة" just works.

1. WHEN the user tells the agent a preference or a fact, THE SYSTEM SHALL store it in long-term memory (Mem0).
2. WHEN the user sends a message, THE SYSTEM SHALL recall relevant facts and use them (e.g. no sugar → sweetener).
3. WHEN the user asks "what do you know about me?", THE SYSTEM SHALL list what it remembers; WHEN the user asks to forget, THE SYSTEM SHALL delete it.
4. THE SYSTEM SHALL NOT store sensitive details (ID numbers, card numbers, health) in memory.

## Requirement 6: Reliable agent

1. THE SYSTEM SHALL use Claude on Amazon Bedrock as the agent's LLM.
2. WHERE `LLM_PROVIDER=openrouter` is set, THE SYSTEM SHALL use the OpenRouter fallback models instead.

## Requirement 7 (next, not demoed): Reminders and deals

1. WHEN a usual item is predicted to run out, THE SYSTEM SHALL send at most one reminder per day, never 22:00–08:00.
2. THE SYSTEM SHALL offer a discount only when the uplift model predicts it changes the outcome, at most once a week.

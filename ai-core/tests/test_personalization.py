"""Personalization layer + guardrails + tools, no LLM needed: .venv/bin/python -m pytest -q"""
import datetime as dt

import pytest

from agent.personalization import guardrails as g
from agent.personalization.layer import PersonalizationLayer
from agent.personalization.repurchase import due_items, similar_user_staples
from agent.store import Store
from agent.tools import Tools

NOW = dt.datetime(2026, 11, 22, 10, 0)


class NoMemory:
    def all(self, user_id):
        return []


@pytest.fixture(scope="module")
def layer(tmp_path_factory):
    return PersonalizationLayer(Store(tmp_path_factory.mktemp("state")))


@pytest.fixture()
def store(tmp_path):
    return Store(tmp_path)


def test_repurchase_finds_running_out_items(layer):
    due = due_items(layer.store, "um_khaled", NOW)
    assert due and all(p["due_score"] >= 0.9 for p in due)
    milk = next(p for p in due if p["item_id"] == "milk")
    assert milk["source"] == "own history" and 3 <= milk["median_gap_days"] <= 5


def test_cold_start_uses_similar_users(layer):
    a = layer.advise("new_user", NOW)
    assert a["cold_start"] and not a["running_out"]
    assert len(similar_user_staples(layer.store, "new_user")) == 5


def test_uplift_offers_only_where_it_changes_behavior(layer):
    assert layer.advise("um_khaled", NOW)["offer"] is None      # orders every few days anyway
    assert layer.advise("new_user", NOW)["offer"] is not None   # infrequent and price-sensitive


def test_bandit_learns_from_replies(tmp_path):
    lay = PersonalizationLayer(Store(tmp_path))
    ctx = lay.context("um_khaled", NOW, 3)
    style, before = lay.bandit.choose(ctx)
    for _ in range(30):
        lay.bandit.update(style, "no", ctx)
    _, after = lay.bandit.choose(ctx)
    assert after[style] < before[style]


def test_reminder_guardrails(store):
    assert not g.can_remind(store, "um_khaled", NOW.replace(hour=23))[0]
    assert not g.can_remind(store, "um_khaled", NOW.replace(hour=7))[0]
    assert g.can_remind(store, "um_khaled", NOW)[0]
    store.log("um_khaled", "reminder", NOW, style="gentle", context=[0] * 5)
    ok, reason = g.can_remind(store, "um_khaled", NOW.replace(hour=15))
    assert not ok and "today" in reason


def test_offer_at_most_weekly(store):
    store.log("um_khaled", "offer", NOW - dt.timedelta(days=3))
    assert not g.can_offer(store, "um_khaled", NOW)[0]
    assert g.can_offer(store, "um_khaled", NOW + dt.timedelta(days=5))[0]


def test_no_order_without_confirmation(store):
    tools = Tools(store, NoMemory())
    ctx = {"user_id": "um_khaled", "now": NOW, "text": "بدي خبز", "turn": 1}
    tools.run("add_to_cart", {"item_id": "bread_small", "qty": 2}, ctx)
    assert "BLOCKED" in tools.run("place_order", {"confirmed_by": "Khaled"}, ctx)["error"]     # not requested yet
    assert tools.run("request_confirmation", {"by": "user"}, ctx)["status"] == "waiting"
    assert "BLOCKED" in tools.run("place_order", {"confirmed_by": "user"}, ctx)["error"]       # same message
    ctx2 = dict(ctx, text="لا مش هلا", turn=2)
    assert "BLOCKED" in tools.run("place_order", {"confirmed_by": "user"}, ctx2)["error"]      # she said no
    ctx3 = dict(ctx, text="اه اطلبه", turn=3)
    assert tools.run("place_order", {"confirmed_by": "user"}, ctx3)["status"] == "ordered"
    assert "BLOCKED" in tools.run("place_order", {"confirmed_by": "Abu Khaled"}, ctx3)["error"]  # empty cart now


def test_family_member_without_permission_cannot_confirm(store):
    tools = Tools(store, NoMemory())
    ctx = {"user_id": "um_khaled", "now": NOW, "text": "", "turn": 1}
    tools.run("add_to_cart", {"item_id": "rice"}, ctx)
    assert "error" in tools.run("request_confirmation", {"by": "Abu Khaled"}, ctx)


def test_spend_cap(store):
    store.cart("um_khaled")["olive_oil"] = 9  # 54 JOD, over the 50 JOD cap
    store.state["pending"]["um_khaled"] = {"by": "Khaled", "turn": 0}
    ok, reason = g.can_place_order(store, "um_khaled", "Khaled")
    assert not ok and "cap" in reason


def test_catalog_search_arabic_and_english(store):
    tools = Tools(store, NoMemory())
    ids = lambda q: [r["item_id"] for r in tools.run("search_catalog", {"query": q}, {})["results"]]
    assert "rice" in ids("رز") and "bread_small" in ids("خبز") and "olive_oil" in ids("olive oil")


def test_sensitive_details_are_not_remembered():
    assert not g.safe_to_remember("رقمي الوطني 9851234567")[0]
    assert not g.safe_to_remember("my husband has diabetes")[0]
    assert g.safe_to_remember("بدون سكر لزوجي")[0]


def test_reminder_is_recorded_only_when_sent(tmp_path):
    lay = PersonalizationLayer(Store(tmp_path))
    advice, _, reason = lay.reminder("um_khaled", NOW)
    assert advice and reason == "ok" and not lay.store.events("um_khaled", "reminder")
    lay.record_reminder("um_khaled", NOW, advice)
    assert lay.reminder("um_khaled", NOW.replace(hour=12))[0] is None  # one per day
    assert lay.feedback("um_khaled", "yes", NOW)["style"] == advice["style"]


def test_llm_cannot_approve_for_family(store):
    tools = Tools(store, NoMemory())
    ctx = {"user_id": "um_khaled", "now": NOW, "text": "", "turn": 1}
    tools.run("add_to_cart", {"item_id": "rice"}, ctx)
    tools.run("request_confirmation", {"by": "Khaled"}, ctx)
    assert "BLOCKED" in tools.run("place_order", {"confirmed_by": "Khaled"}, dict(ctx, turn=2))["error"]
    assert not g.can_place_order(store, "um_khaled", "Um Khaled", "اه")[0]   # asked Khaled, not her
    assert g.can_place_order(store, "um_khaled", "Khaled")[0]                 # Khaled's own approval


def test_cart_change_cancels_confirmation(store):
    tools = Tools(store, NoMemory())
    ctx = {"user_id": "um_khaled", "now": NOW, "text": "", "turn": 1}
    tools.run("add_to_cart", {"item_id": "rice"}, ctx)
    tools.run("request_confirmation", {"by": "Khaled"}, ctx)
    tools.run("add_to_cart", {"item_id": "olive_oil", "qty": 3}, ctx)
    assert not store.state["pending"].get("um_khaled")
    assert not g.can_place_order(store, "um_khaled", "Khaled")[0]


def test_consent_needs_a_clear_yes():
    for yes in ("اه", "اه اطلبه", "تمام", "yes please", "ok go ahead", "أكيد، اطلبه", "آه تمام!", "order it", "اه يا ابني اطلبه", "تمام يسلمو", "اه يا ريت"):
        assert g.says_yes(yes), yes
    for no in ("مش تمام", "لا", "لا تطلب", "الاهم الخبز", "not yet", "no, cancel it", "ما بدي",
               "لا، اطلبه بعدين", "لأ؛ تمام", "مو هلا، اطلب", "لاء اطلبه", "تمام؟ لا", "no.ok", "ok?no",
               "ok never mind", "yes but hold on", "تمام بس استنى", "اه بس شيل الرز", "ok but remove the rice"):
        assert not g.says_yes(no), no

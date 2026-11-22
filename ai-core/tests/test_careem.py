"""Careem flows through a real careem-mcp sandbox server (no LLM): the tests play the model's tool calls."""
import datetime as dt
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

from agent.careem import LLM_TOOLS, SPENDING, CareemMCP, CareemTools
from agent.personalization import guardrails as g
from agent.personalization import services
from agent.store import Store

ROOT = Path(__file__).resolve().parents[1]
NOW = dt.datetime(2026, 11, 24, 9, 10)  # a Tuesday morning
HOME = {"latitude": 25.0866, "longitude": 55.1474}


class NoMemory:
    def all(self, user_id):
        return []


@pytest.fixture(scope="module")
def mcp(tmp_path_factory):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    overrides = tmp_path_factory.mktemp("run") / "overrides.json"
    overrides.write_text("{}")
    p = subprocess.Popen([sys.executable, str(ROOT / "careem-mcp-sandbox" / "server.py"), "--port", str(port)],
                         env=dict(os.environ, CAREEM_MCP_OVERRIDES=str(overrides)),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1)
            break
        except OSError:
            time.sleep(0.1)
    yield CareemMCP(f"http://127.0.0.1:{port}/mcp")
    p.terminate()


@pytest.fixture()
def tools(mcp, tmp_path):
    return CareemTools(Store(tmp_path), NoMemory(), services.load()["places"], mcp)


CART = {"merchant_id": 40001, **HOME, "items": [{"keyword": "milk", "catalog_item_id": "4000101", "quantity": 2}]}
BOX_QUOTE = {"pickup_latitude": 25.0866, "pickup_longitude": 55.1474, "dropoff_latitude": 25.2172,
             "dropoff_longitude": 55.2826, "cct_id": 1502}
BOX_ORDER = {"pickup_latitude": 25.0866, "pickup_longitude": 55.1474, "pickup_location_id": "LOC-50001",
             "dropoff_location_id": "LOC-50002", "cct_id": 1502, "payment_type": "cash"}


def ctx(turn, text=""):
    return {"user_id": "um_khaled", "now": NOW, "text": text, "turn": turn}


def test_llm_never_gets_spending_tools(tools):
    names = {s["function"]["name"] for s in tools.schemas()}
    assert set(LLM_TOOLS) <= names and not names & {"cart_grocery_checkout", "cart_checkout", "box_create_order", "rides_request"}
    assert "BLOCKED" in tools.run("cart_grocery_checkout", {"basket_id": 6000002}, ctx(1))["error"]


def test_grocery_order_with_users_own_yes(tools):
    found = tools.run("search_groceries_items", {"search_terms": ["milk"], **HOME}, ctx(1))
    assert "error" not in found
    cart = tools.run("create_grocery_cart_with_quantities", {"merchant_id": 40001, **HOME,
                     "items": [{"keyword": "milk", "catalog_item_id": "4000101", "quantity": 2}]}, ctx(1))
    assert "error" not in cart
    tools.run("cart_get_basket_price", {"merchant_id": 40001, **HOME}, ctx(1))
    checkout = {"basket_id": 6000002, "total_price": 45.5, "payment_type": "cash", **HOME}
    r = tools.run("request_confirmation", {"by": "user", "checkout_tool": "cart_grocery_checkout", "checkout_args": checkout,
                                           "total": 45.5, "currency": "AED", "summary": "2x milk, eggs, sourdough"}, ctx(1))
    assert r["status"] == "waiting"
    assert "BLOCKED" in tools.run("place_order", {"confirmed_by": "user"}, ctx(1, "اه"))["error"]          # same message
    assert "BLOCKED" in tools.run("place_order", {"confirmed_by": "user"}, ctx(2, "لا مش هلا"))["error"]   # a no
    done = tools.run("place_order", {"confirmed_by": "user"}, ctx(3, "اه اطلبه"))
    assert done["status"] == "ordered" and done["service"] == "groceries"
    assert tools.store.state["service_orders"][-1]["ok"] and not tools.store.state["pending"]


def test_changing_the_cart_cancels_the_confirmation(tools):
    tools.run("create_grocery_cart_with_quantities", CART, ctx(1))
    tools.run("cart_get_basket_price", {"merchant_id": 40001, **HOME}, ctx(1))
    tools.run("request_confirmation", {"by": "user", "checkout_tool": "cart_grocery_checkout", "total": 45.5, "summary": "x", "currency": "AED",
                                       "checkout_args": {"basket_id": 6000002, "total_price": 45.5, **HOME}}, ctx(1))
    assert tools.store.state["pending"]["um_khaled"]
    tools.run("create_grocery_cart_with_quantities", {"merchant_id": 40001, **HOME,
              "items": [{"keyword": "yogurt", "catalog_item_id": "4000107", "quantity": 1}]}, ctx(2))
    assert not tools.store.state["pending"]


def test_bad_checkout_args_are_rejected(tools):
    r = tools.run("request_confirmation", {"by": "user", "checkout_tool": "cart_grocery_checkout", "total": 10,
                                           "summary": "x", "checkout_args": {"basket_id": "abc"}}, ctx(1))
    assert "do not fit" in r["error"]


def test_box_delivery_needs_family_approval(tools):
    quote = tools.run("box_pre_checkout", BOX_QUOTE, ctx(1))
    assert quote["delivery_estimate"]["currency_code"] == "AED"
    r = tools.run("request_confirmation", {"by": "Khaled", "checkout_tool": "box_create_order", "checkout_args": dict(BOX_ORDER),
                                           "total": 52, "currency": "AED", "summary": "Box by car, Home to Work"}, ctx(1))
    assert r["status"] == "waiting"
    assert "BLOCKED" in tools.run("place_order", {"confirmed_by": "Khaled"}, ctx(2, "yes"))["error"]  # LLM cannot approve for him
    assert g.can_place_order(tools.store, "um_khaled", "Khaled")[0]                                  # his app can
    done = tools.execute_pending("um_khaled", "Khaled", NOW)
    assert done["status"] == "ordered" and done["service"] == "box"


def test_ride_quote_and_booking(tools):
    q = tools.run("rides_get_quote", {"pickup": "Home", "dropoff": "Dubai Mall"}, ctx(1))
    assert q["distance_km"] > 5 and {x["product"] for x in q["quotes"]} == {"Go", "Comfort", "Business"}
    price = next(x["price_aed"] for x in q["quotes"] if x["product"] == "Comfort")
    r = tools.run("request_confirmation", {"by": "user", "checkout_tool": "rides_request", "total": price, "currency": "AED",
                                           "summary": "Comfort ride", "checkout_args": {"quote_id": q["quote_id"], "product": "Comfort"}}, ctx(1))
    assert r["status"] == "waiting"
    done = tools.run("place_order", {"confirmed_by": "user"}, ctx(2, "تمام"))
    assert done["status"] == "ordered" and done["result"]["captain"]
    assert "unknown place" in tools.run("rides_get_quote", {"pickup": "Home", "dropoff": "Mars"}, ctx(3))["error"]


def test_spend_cap_in_aed(tools):
    tools.store.state["pending"]["um_khaled"] = {"by": "Khaled", "tool": "box_create_order", "total": 300.0, "currency": "AED"}  # over the 259 AED (~50 JOD) cap
    ok, reason = g.can_place_order(tools.store, "um_khaled", "Khaled")
    assert not ok and "cap" in reason


def test_nan_and_wrong_basket_totals_fail_closed(tools):
    tools.run("create_grocery_cart_with_quantities", CART, ctx(1))
    tools.run("cart_get_basket_price", {"merchant_id": 40001, **HOME}, ctx(1))
    for bad in (float("nan"), 1.0, -45.5):
        r = tools.run("request_confirmation", {"by": "user", "checkout_tool": "cart_grocery_checkout", "total": bad, "currency": "AED",
                                               "summary": "x", "checkout_args": {"basket_id": 6000002, "total_price": bad, **HOME}}, ctx(2))
        assert "error" in r and not tools.store.state["pending"]
    tools.store.state["pending"]["um_khaled"] = {"by": "Khaled", "tool": "box_create_order", "total": float("nan"), "currency": "AED"}
    assert not g.can_place_order(tools.store, "um_khaled", "Khaled")[0]


def test_usual_ride_and_box_predictions():
    data = services.load()
    ride = services.usual_ride(data, "um_khaled", NOW)
    assert (ride["from"], ride["to"], ride["product"]) == ("Home", "Dubai Mall", "Comfort")
    assert services.usual_ride(data, "um_khaled", NOW.replace(hour=20)) is None
    box = services.usual_box(data, "um_khaled", NOW)
    assert (box["from"], box["to"], box["vehicle"]) == ("Home", "Work", "Car")
    assert services.usual_ride(data, "new_user", NOW) is None and services.usual_box(data, "new_user", NOW) is None


def test_other_service_does_not_cancel_a_pending_ride(tools):
    q = tools.run("rides_get_quote", {"pickup": "Home", "dropoff": "Work"}, ctx(1))
    go = next(x["price_aed"] for x in q["quotes"] if x["product"] == "Go")
    tools.run("request_confirmation", {"by": "Khaled", "checkout_tool": "rides_request", "total": go, "currency": "AED",
                                       "summary": "ride", "checkout_args": {"quote_id": q["quote_id"], "product": "Go"}}, ctx(1))
    tools.run("create_grocery_cart_with_quantities", {"merchant_id": 40001, **HOME,
              "items": [{"keyword": "milk", "catalog_item_id": "4000101", "quantity": 1}]}, ctx(2))
    assert tools.store.state["pending"]["um_khaled"]["tool"] == "rides_request"


def test_extra_quote_fields_are_dropped_from_checkout(tools):
    tools.run("box_pre_checkout", BOX_QUOTE, ctx(1))
    order = dict(BOX_ORDER, dropoff_latitude=25.2172, dropoff_name="Work")
    r = tools.run("request_confirmation", {"by": "Khaled", "checkout_tool": "box_create_order", "checkout_args": order,
                                           "total": 52, "currency": "AED", "summary": "Box"}, ctx(1))
    assert r["status"] == "waiting" and "dropoff_name" not in tools.store.state["pending"]["um_khaled"]["args"]
    assert "nothing is waiting" in g.can_place_order(Store(tools.store.state_dir / "x"), "um_khaled", "Khaled")[1]


def test_price_comes_from_careem_not_the_model(tools):
    q = tools.run("rides_get_quote", {"pickup": "Home", "dropoff": "Airport T3"}, ctx(1))
    r = tools.run("request_confirmation", {"by": "user", "checkout_tool": "rides_request", "total": 5, "currency": "AED",
                                           "summary": "cheap ride", "checkout_args": {"quote_id": q["quote_id"], "product": "Business"}}, ctx(1))
    assert "according to Careem" in r["error"] and not tools.store.state["pending"]
    r = tools.run("request_confirmation", {"by": "Khaled", "checkout_tool": "box_create_order", "checkout_args": dict(BOX_ORDER),
                                           "total": 52, "currency": "AED", "summary": "Box"}, ctx(2))
    assert "box_pre_checkout first" in r["error"]  # no quote for this delivery yet
    r = tools.run("request_confirmation", {"by": "user", "checkout_tool": "cart_grocery_checkout", "total": 45.5, "currency": "AED",
                                           "summary": "x", "checkout_args": {"basket_id": 6000002, "total_price": 45.5, **HOME}}, ctx(3))
    assert "price this basket first" in r["error"]


def test_unknown_currency_fails_closed(tools):
    tools.store.state["pending"]["um_khaled"] = {"by": "Khaled", "tool": "box_create_order", "total": 1, "currency": "XYZ"}
    ok, reason = g.can_place_order(tools.store, "um_khaled", "Khaled")
    assert not ok and "unknown currency" in reason


def test_checkout_switch_defaults(monkeypatch):
    from agent.careem_mcp import checkout_allowed, is_production
    monkeypatch.delenv("CAREEM_ALLOW_CHECKOUT", raising=False)
    monkeypatch.setenv("CAREEM_MCP_URL", "https://mcp.careemapis.com/mcp")
    assert is_production() and not checkout_allowed()          # real Careem: off unless switched on
    monkeypatch.setenv("CAREEM_MCP_URL", "http://127.0.0.1:8787/mcp")
    assert not is_production() and checkout_allowed()          # local sandbox: on
    monkeypatch.setenv("CAREEM_ALLOW_CHECKOUT", "false")
    assert not checkout_allowed()


def test_checkout_off_builds_but_never_pays(tools, monkeypatch):
    monkeypatch.setenv("CAREEM_ALLOW_CHECKOUT", "false")
    tools.run("box_pre_checkout", BOX_QUOTE, ctx(1))
    tools.run("request_confirmation", {"by": "Khaled", "checkout_tool": "box_create_order", "checkout_args": dict(BOX_ORDER),
                                       "total": 52, "currency": "AED", "summary": "Box"}, ctx(1))
    calls = []
    real_call = tools.mcp.call
    tools.mcp.call = lambda name, args: calls.append(name) or real_call(name, args)
    r = tools.execute_pending("um_khaled", "Khaled", NOW)
    assert r["status"] == "blocked" and "nothing was paid" in r["result"]["error"]
    assert "box_create_order" not in calls and not tools.store.state["pending"]


def test_users_yes_places_the_waiting_order_without_the_model(tools, monkeypatch):
    from agent.brain import Brain

    class NoLLM:
        calls = 0

        def chat(self, messages, tools=None):
            from agent.llm import Message
            return Message("done"), {"model": "test"}

    class Layer:
        def advise(self, user_id, now):
            return {"running_out": [], "cold_start": False, "suggestions_for_new_user": [], "usual_ride": None,
                    "usual_box": None, "style": "short", "style_hint": "", "style_scores": {}, "offer": None,
                    "offer_decision": {}}

    class Mem:
        def seed(self, u): pass
        def recall(self, u, t): return []
        def learn(self, u, t): return True, "ok"

    q = tools.run("rides_get_quote", {"pickup": "Home", "dropoff": "Work", "product": "Go"}, ctx(1))
    price = q["quotes"][0]["price_aed"]
    tools.run("request_confirmation", {"by": "user", "checkout_tool": "rides_request", "total": price, "currency": "AED",
                                       "summary": "Go to work", "checkout_args": {"quote_id": q["quote_id"], "product": "Go"}}, ctx(0))
    brain = Brain(tools.store, Mem(), Layer(), tools, NoLLM())
    out = brain.handle("um_khaled", "yep, go ahead and book it please", NOW)
    auto = [s for s in out["steps"] if s.get("tool") == "place_order"]
    assert auto and auto[0]["result"]["status"] == "ordered" and not tools.store.state["pending"]


def test_a_late_yes_does_not_place_the_order(tools):
    from agent.brain import Brain
    from agent.llm import Message

    class NoLLM:
        def chat(self, messages, tools=None):
            return Message("ok"), {"model": "test"}

    class Layer:
        def advise(self, user_id, now):
            return {"running_out": [], "cold_start": False, "suggestions_for_new_user": [], "usual_ride": None,
                    "usual_box": None, "style": "short", "style_hint": "", "style_scores": {}, "offer": None,
                    "offer_decision": {}}

    class Mem:
        def seed(self, u): pass
        def recall(self, u, t): return []
        def learn(self, u, t): return True, "ok"

    brain = Brain(tools.store, Mem(), Layer(), tools, NoLLM())
    q = tools.run("rides_get_quote", {"pickup": "Home", "dropoff": "Work", "product": "Go"}, ctx(1))
    tools.run("request_confirmation", {"by": "user", "checkout_tool": "rides_request", "total": q["quotes"][0]["price_aed"],
                                       "currency": "AED", "summary": "Go", "checkout_args": {"quote_id": q["quote_id"], "product": "Go"}},
              ctx(1))
    brain.turns["um_khaled"] = 1
    brain.handle("um_khaled", "صح؟", NOW)                                  # a question: no order
    assert tools.store.state["pending"]
    late = NOW + __import__("datetime").timedelta(hours=2)
    out = brain.handle("um_khaled", "اه اطلبه", late)                      # too late: no order
    assert not [s for s in out["steps"] if s.get("tool") == "place_order"] and tools.store.state["pending"]

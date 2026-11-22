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
    checkout = {"basket_id": 6000002, "total_price": 45.5, "payment_type": "cash", **HOME}
    r = tools.run("request_confirmation", {"by": "user", "checkout_tool": "cart_grocery_checkout", "checkout_args": checkout,
                                           "total": 45.5, "summary": "2x milk, eggs, sourdough"}, ctx(1))
    assert r["status"] == "waiting"
    assert "BLOCKED" in tools.run("place_order", {"confirmed_by": "user"}, ctx(1, "اه"))["error"]          # same message
    assert "BLOCKED" in tools.run("place_order", {"confirmed_by": "user"}, ctx(2, "لا مش هلا"))["error"]   # a no
    done = tools.run("place_order", {"confirmed_by": "user"}, ctx(3, "اه اطلبه"))
    assert done["status"] == "ordered" and done["service"] == "groceries"
    assert tools.store.state["service_orders"][-1]["ok"] and not tools.store.state["pending"]


def test_changing_the_cart_cancels_the_confirmation(tools):
    tools.run("request_confirmation", {"by": "user", "checkout_tool": "cart_grocery_checkout", "total": 45.5, "summary": "x",
                                       "checkout_args": {"basket_id": 6000002, "total_price": 45.5, **HOME}}, ctx(1))
    tools.run("create_grocery_cart_with_quantities", {"merchant_id": 40001, **HOME,
              "items": [{"keyword": "yogurt", "catalog_item_id": "4000107", "quantity": 1}]}, ctx(2))
    assert not tools.store.state["pending"]


def test_bad_checkout_args_are_rejected(tools):
    r = tools.run("request_confirmation", {"by": "user", "checkout_tool": "cart_grocery_checkout", "total": 10,
                                           "summary": "x", "checkout_args": {"basket_id": "abc"}}, ctx(1))
    assert "do not fit" in r["error"]


def test_box_delivery_needs_family_approval(tools):
    quote = tools.run("box_pre_checkout", {"pickup_latitude": 25.0866, "pickup_longitude": 55.1474, "dropoff_latitude": 25.2172,
                                           "dropoff_longitude": 55.2826, "cct_id": 1502}, ctx(1))
    assert quote["delivery_estimate"]["currency_code"] == "AED"
    order = {"pickup_latitude": 25.0866, "pickup_longitude": 55.1474, "pickup_location_id": "LOC-50001",
             "dropoff_location_id": "LOC-50002", "cct_id": 1502, "payment_type": "cash"}
    r = tools.run("request_confirmation", {"by": "Khaled", "checkout_tool": "box_create_order", "checkout_args": order,
                                           "total": 52, "summary": "Box by car, Home to Work"}, ctx(1))
    assert r["status"] == "waiting"
    assert "BLOCKED" in tools.run("place_order", {"confirmed_by": "Khaled"}, ctx(2, "yes"))["error"]  # LLM cannot approve for him
    assert g.can_place_order(tools.store, "um_khaled", "Khaled")[0]                                  # his app can
    done = tools.execute_pending("um_khaled", "Khaled", NOW)
    assert done["status"] == "ordered" and done["service"] == "box"


def test_ride_quote_and_booking(tools):
    q = tools.run("rides_get_quote", {"pickup": "Home", "dropoff": "Dubai Mall"}, ctx(1))
    assert q["distance_km"] > 5 and {x["product"] for x in q["quotes"]} == {"Go", "Comfort", "Business"}
    r = tools.run("request_confirmation", {"by": "user", "checkout_tool": "rides_request", "total": 40, "summary": "Comfort ride",
                                           "checkout_args": {"quote_id": q["quote_id"], "product": "Comfort"}}, ctx(1))
    assert r["status"] == "waiting"
    done = tools.run("place_order", {"confirmed_by": "user"}, ctx(2, "تمام"))
    assert done["status"] == "ordered" and done["result"]["captain"]
    assert "unknown place" in tools.run("rides_get_quote", {"pickup": "Home", "dropoff": "Mars"}, ctx(3))["error"]


def test_spend_cap_in_aed(tools):
    tools.run("request_confirmation", {"by": "Khaled", "checkout_tool": "cart_grocery_checkout", "total": 200, "summary": "big",
                                       "checkout_args": {"basket_id": 6000002, "total_price": 200, **HOME}}, ctx(1))
    ok, reason = g.can_place_order(tools.store, "um_khaled", "Khaled")
    assert not ok and "cap" in reason


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
    tools.run("request_confirmation", {"by": "Khaled", "checkout_tool": "rides_request", "total": 40, "summary": "ride",
                                       "checkout_args": {"quote_id": q["quote_id"], "product": "Go"}}, ctx(1))
    tools.run("create_grocery_cart_with_quantities", {"merchant_id": 40001, **HOME,
              "items": [{"keyword": "milk", "catalog_item_id": "4000101", "quantity": 1}]}, ctx(2))
    assert tools.store.state["pending"]["um_khaled"]["tool"] == "rides_request"


def test_extra_quote_fields_are_dropped_from_checkout(tools):
    order = {"pickup_latitude": 25.0866, "pickup_longitude": 55.1474, "pickup_location_id": "LOC-50001",
             "dropoff_location_id": "LOC-50002", "cct_id": 1502, "payment_type": "cash",
             "dropoff_latitude": 25.2172, "dropoff_name": "Work"}
    r = tools.run("request_confirmation", {"by": "Khaled", "checkout_tool": "box_create_order", "checkout_args": order,
                                           "total": 52, "summary": "Box"}, ctx(1))
    assert r["status"] == "waiting" and "dropoff_name" not in tools.store.state["pending"]["um_khaled"]["args"]
    assert "nothing is waiting" in g.can_place_order(Store(tools.store.state_dir / "x"), "um_khaled", "Khaled")[1]

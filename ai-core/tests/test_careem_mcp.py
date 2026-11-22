"""Careem MCP tools + confirm gate against a fake MCP server (no network, no LLM)."""
import datetime as dt

from agent.careem_mcp import CHECKOUT, CareemMCPTools
from agent.store import Store
from agent.tools import Tools

NOW = dt.datetime(2026, 11, 22, 12, 0)


class FakeCareem:
    def __init__(self, total=4.25):
        self.calls, self.total = [], total
        self.fail_checkout = False

    def list_tools(self):
        obj = {"type": "object"}
        return [
            {"name": "user_info", "description": "User and saved addresses", "inputSchema": obj},
            {"name": "search_groceries_items", "description": "Search", "inputSchema": obj},
            {"name": "create_grocery_cart_with_quantities", "description": "Create cart", "inputSchema": obj},
            {"name": "cart_get_basket_price", "description": "Price", "inputSchema": obj},
            {"name": "cart_checkout", "description": "Food checkout (spends money)", "inputSchema": obj},
            {"name": "create_ride", "description": "Books a real captain", "inputSchema": obj},
            {"name": CHECKOUT, "description": "Checkout",
             "inputSchema": {"type": "object", "properties": {"cart_id": {}, "lat": {}, "lng": {}, "total_price": {}},
                             "required": ["cart_id", "lat", "lng", "total_price"]}},
        ]

    def call(self, name, args):
        self.calls.append((name, args))
        if name == "user_info":
            return {"addresses": [{"label": "home", "lat": 31.95, "lng": 35.91}]}
        if name == "create_grocery_cart_with_quantities":
            return {"cart": {"cart_id": "C42"}}
        if name == "cart_get_basket_price":
            return {"cart_id": "C42", "total": self.total, "currency": "JOD"}
        if name == CHECKOUT:
            if self.fail_checkout:
                raise TimeoutError("network")
            return {"order_id": "O1", "eta_min": 25}
        return {"results": []}


class NoMemory:
    def all(self, user_id):
        return []


def setup(tmp_path, total=4.25):
    store, fake = Store(tmp_path), FakeCareem(total)
    tools = CareemMCPTools(store, NoMemory(), Tools(store, NoMemory()), connector=fake)
    return store, fake, tools


def ctx(turn, text=""):
    return {"user_id": "um_khaled", "now": NOW, "turn": turn, "text": text}


def build_cart(tools, turn=1):
    tools.run("user_info", {}, ctx(turn))
    tools.run("create_grocery_cart_with_quantities", {"lat": 31.95, "lng": 35.91, "items": [{"id": "bread", "qty": 2}]}, ctx(turn))
    tools.run("cart_get_basket_price", {"cart_id": "C42"}, ctx(turn))


def checkouts(fake):
    return [c for c in fake.calls if c[0] == CHECKOUT]


def test_llm_never_sees_or_calls_checkout(tmp_path):
    store, fake, tools = setup(tmp_path)
    names = [s["function"]["name"] for s in tools.schemas()]
    assert CHECKOUT not in names and "request_confirmation" in names and "user_info" in names
    assert "cart_checkout" not in names and "create_ride" not in names  # nothing else that spends money
    assert "BLOCKED" in tools.run(CHECKOUT, {"cart_id": "C42"}, ctx(1))["error"]
    assert "not available" in tools.run("cart_checkout", {}, ctx(1))["error"]
    assert [c for c in fake.calls if c[0] in ("cart_checkout", CHECKOUT)] == []


def test_user_yes_in_next_message_checks_out_once_with_seen_args(tmp_path):
    store, fake, tools = setup(tmp_path)
    build_cart(tools)
    assert tools.run("request_confirmation", {"by": "user"}, ctx(1))["status"] == "waiting"
    assert "next message" in tools.run("place_order", {"confirmed_by": "user"}, ctx(1, "اه"))["error"]
    r = tools.run("place_order", {"confirmed_by": "user"}, ctx(2, "اه يا ريت"))
    assert r["status"] == "ordered"
    assert checkouts(fake) == [(CHECKOUT, {"cart_id": "C42", "lat": 31.95, "lng": 35.91, "total_price": 4.25})]
    # a second yes cannot order again
    assert "error" in tools.run("place_order", {"confirmed_by": "user"}, ctx(3, "اه"))
    assert len(checkouts(fake)) == 1


def test_unclear_answer_blocks(tmp_path):
    store, fake, tools = setup(tmp_path)
    build_cart(tools)
    tools.run("request_confirmation", {"by": "user"}, ctx(1))
    assert "BLOCKED" in tools.run("place_order", {"confirmed_by": "user"}, ctx(2, "لا استنى"))["error"]
    assert checkouts(fake) == []


def test_cart_change_needs_new_price_and_confirmation(tmp_path):
    store, fake, tools = setup(tmp_path)
    build_cart(tools)
    tools.run("request_confirmation", {"by": "user"}, ctx(1))
    tools.run("create_grocery_cart_with_quantities", {"lat": 31.95, "lng": 35.91, "items": []}, ctx(2))
    assert "BLOCKED" in tools.run("place_order", {"confirmed_by": "user"}, ctx(2, "اه"))["error"]
    assert "error" in tools.run("request_confirmation", {"by": "user"}, ctx(2))  # no price yet
    assert checkouts(fake) == []


def test_family_cannot_approve_through_llm_only_in_app(tmp_path):
    store, fake, tools = setup(tmp_path)
    build_cart(tools)
    tools.run("request_confirmation", {"by": "Khaled"}, ctx(1))
    assert "BLOCKED" in tools.run("place_order", {"confirmed_by": "Khaled"}, ctx(2, "اه"))["error"]
    assert tools.family_checkout("um_khaled", "Abu Khaled", NOW)["status"] == "blocked"
    assert tools.family_checkout("um_khaled", "Khaled", NOW)["status"] == "ordered"
    assert len(checkouts(fake)) == 1


def test_spend_cap(tmp_path):
    store, fake, tools = setup(tmp_path, total=55.0)
    build_cart(tools)
    tools.run("request_confirmation", {"by": "Khaled"}, ctx(1))
    assert "cap" in tools.family_checkout("um_khaled", "Khaled", NOW)["reason"]


def test_failed_checkout_is_not_retried(tmp_path):
    store, fake, tools = setup(tmp_path)
    fake.fail_checkout = True
    build_cart(tools)
    tools.run("request_confirmation", {"by": "Khaled"}, ctx(1))
    r = tools.family_checkout("um_khaled", "Khaled", NOW)
    assert r["status"] == "error" and "NOT retried" in r["error"]
    fake.fail_checkout = False
    assert "already failed" in tools.family_checkout("um_khaled", "Khaled", NOW)["error"]  # second tap
    assert len(checkouts(fake)) == 1

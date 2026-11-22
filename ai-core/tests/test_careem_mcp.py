"""Careem MCP tools + confirm gate against a fake MCP server (no network, no LLM)."""
import datetime as dt

from agent.careem_mcp import CHECKOUT, CareemMCPTools
from agent.store import Store
from agent.tools import Tools

NOW = dt.datetime(2026, 11, 22, 12, 0)


class FakeCareem:
    def __init__(self, total=4.25, currency="JOD"):
        self.calls, self.total, self.currency = [], total, currency
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
            return {"cart_id": "C42", "total": self.total, "currency": self.currency}
        if name == CHECKOUT:
            if self.fail_checkout:
                raise TimeoutError("network")
            return {"order_id": "O1", "eta_min": 25}
        return {"results": []}


class NoMemory:
    def all(self, user_id):
        return []


def setup(tmp_path, total=4.25, currency="JOD"):
    store, fake = Store(tmp_path), FakeCareem(total, currency)
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


def test_spend_cap_converts_sandbox_aed(tmp_path):
    store, fake, tools = setup(tmp_path, total=60.0, currency="AED")  # about 11.6 JOD: under the 50 JOD cap
    build_cart(tools)
    tools.run("request_confirmation", {"by": "Khaled"}, ctx(1))
    assert tools.family_checkout("um_khaled", "Khaled", NOW)["status"] == "ordered"
    store, fake, tools = setup(tmp_path / "b", total=300.0, currency="AED")  # about 57.9 JOD: over
    build_cart(tools)
    tools.run("request_confirmation", {"by": "Khaled"}, ctx(1))
    assert "cap" in tools.family_checkout("um_khaled", "Khaled", NOW)["reason"]


def test_checkout_args_use_sandbox_names_for_timezone_and_payment(tmp_path):
    """Careem names: user_info.city_timezone -> timezone, price payment_method.{id,type} -> payment_id/payment_type."""
    store, fake, tools = setup(tmp_path)
    tools.checkout_tool = {"inputSchema": {"type": "object", "required": ["basket_id", "total_price"], "properties": {
        "basket_id": {}, "total_price": {}, "timezone": {}, "currency": {}, "payment_id": {}, "payment_type": {}}}}
    st = tools.st("um_khaled")
    st["seen"].update({"city_timezone": "Asia/Dubai", "city_currency": "AED", "payment_type": "COD"})
    st["basket"] = {"basket": {"id": 6000002}, "price": {"total": 45.5},
                    "payment_method": {"type": "card", "id": 4242}}
    st["seen"]["basket_id"] = 6000002
    args, missing = tools.checkout_args("um_khaled")
    assert missing == []
    assert args == {"basket_id": 6000002, "total_price": 45.5, "timezone": "Asia/Dubai", "currency": "AED",
                    "payment_id": 4242, "payment_type": "card"}  # payment from the priced basket, not the LLM's COD


def test_reading_the_cart_does_not_cancel_confirmation(tmp_path):
    """Live sandbox run: on "yes" the LLM re-read the basket (cart_get_quik_basket) and that wiped the pending order."""
    store, fake, tools = setup(tmp_path)
    build_cart(tools)
    tools.run("request_confirmation", {"by": "user"}, ctx(1))
    tools.remote["cart_get_quik_basket"] = {"name": "cart_get_quik_basket", "description": "", "inputSchema": {}}
    tools.run("cart_get_quik_basket", {}, ctx(2, "اه"))
    tools.run("cart_get_basket_price", {}, ctx(2, "اه"))  # same basket priced again
    assert tools.run("request_confirmation", {"by": "user"}, ctx(2, "اه"))["note"].startswith("already asked")
    r = tools.run("place_order", {"confirmed_by": "user"}, ctx(2, "اه"))
    assert r["status"] == "ordered" and [c for c in fake.calls if c[0] == CHECKOUT]


def test_same_basket_again_is_not_reordered_and_clears_the_request(tmp_path):
    """The static sandbox returns the same basket every time: a second confirmation must not order it again."""
    store, fake, tools = setup(tmp_path)
    build_cart(tools)
    tools.run("request_confirmation", {"by": "user"}, ctx(1))
    assert tools.run("place_order", {"confirmed_by": "user"}, ctx(2, "اه"))["status"] == "ordered"
    tools.run("cart_get_basket_price", {"cart_id": "C42"}, ctx(3))  # identical basket priced again
    tools.run("request_confirmation", {"by": "Khaled"}, ctx(3))
    r = tools.family_checkout("um_khaled", "Khaled", NOW)
    assert r["note"] == "already ordered" and len(checkouts(fake)) == 1
    assert "um_khaled" not in store.state["pending"]


def test_careem_answers_beat_llm_arguments(tmp_path):
    """Live sandbox run: the LLM passed city_id=0 to the price call and checkout got 0 instead of user_info's 1."""
    store, fake, tools = setup(tmp_path)
    tools.checkout_tool = {"inputSchema": {"type": "object", "required": ["cart_id", "lat"],
                                           "properties": {"cart_id": {}, "lat": {}, "city_id": {}}}}
    fake.call = lambda name, args: {"city_id": 1} if name == "user_info" else {"cart_id": "C42"}
    tools.run("user_info", {}, ctx(1))
    tools.run("cart_get_basket_price", {"city_id": 0, "lat": 25.08}, ctx(1))
    args, missing = tools.checkout_args("um_khaled")
    assert args == {"cart_id": "C42", "lat": 25.08, "city_id": 1} and missing == []  # lat only came from args
    # user_info without a location has no city: the LLM's guess is still not used for an optional arg
    store.state["mcp"]["um_khaled"]["seen"].pop("city_id")
    args, missing = tools.checkout_args("um_khaled")
    assert args == {"cart_id": "C42", "lat": 25.08} and missing == []


def test_sandbox_note_only_on_local_sandbox(monkeypatch):
    from agent.brain import sandbox_note
    monkeypatch.setenv("CAREEM_PROVIDER", "mock")
    assert sandbox_note() == ""
    monkeypatch.setenv("CAREEM_PROVIDER", "mcp")
    monkeypatch.setenv("CAREEM_MCP_URL", "http://127.0.0.1:8787/mcp")
    assert "fixed test basket" in sandbox_note()
    monkeypatch.setenv("CAREEM_MCP_URL", "https://mcp.careemapis.com/mcp")
    assert sandbox_note() == ""  # production: the agent must still point out real differences


def test_her_yes_or_khaled_whoever_is_first(tmp_path):
    # asked of her: Khaled's approve also works (first one wins, once)
    store, fake, tools = setup(tmp_path)
    build_cart(tools)
    r = tools.run("request_confirmation", {"by": "user"}, ctx(1))
    assert "can also approve" in r["note"]
    assert tools.family_checkout("um_khaled", "Khaled", NOW)["status"] == "ordered"
    assert "error" in tools.run("place_order", {"confirmed_by": "user"}, ctx(2, "اه"))  # her later yes can't order again
    assert len(checkouts(fake)) == 1
    # asked of her: her own yes works too
    store, fake, tools = setup(tmp_path / "b")
    build_cart(tools)
    tools.run("request_confirmation", {"by": "user"}, ctx(1))
    assert tools.run("place_order", {"confirmed_by": "user"}, ctx(2, "اه"))["status"] == "ordered"
    assert tools.family_checkout("um_khaled", "Khaled", NOW)["status"] == "blocked"  # nothing pending any more
    assert len(checkouts(fake)) == 1


def test_asked_of_khaled_only_khaled(tmp_path):
    store, fake, tools = setup(tmp_path)
    build_cart(tools)
    tools.run("request_confirmation", {"by": "Khaled"}, ctx(1))
    assert "BLOCKED" in tools.run("place_order", {"confirmed_by": "user"}, ctx(2, "اه"))["error"]
    assert tools.family_checkout("um_khaled", "Abu Khaled", NOW)["status"] == "blocked"  # not allowed to confirm
    assert tools.family_checkout("um_khaled", "Khaled", NOW)["status"] == "ordered"

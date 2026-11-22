"""The real MCP connector (SDK 2.x) against an in-process server with the Careem tool names, lat/lng filled in,
unknown total -> family, and the Mem0 temperature fix. No network, no AWS: .venv/bin/python -m pytest -q"""
import datetime as dt

import pytest
from mcp.server.mcpserver import MCPServer

from agent.careem_mcp import CHECKOUT, CareemMCPTools, MCPConnector
from agent.memory import UserMemory
from agent.store import Store
from agent.tools import Tools

NOW = dt.datetime(2026, 11, 22, 12, 0)


def fake_careem(total=4.25, address=True):
    """Same tool names as the Careem groceries journey; argument names are this fake's own."""
    srv, calls = MCPServer("fake-careem"), []

    @srv.tool()
    def user_info() -> dict:
        return {"addresses": [{"label": "home", "lat": 31.99, "lng": 35.87}]} if address else {"name": "Um Khaled"}

    @srv.tool()
    def search_groceries_items(query: str, lat: float, lng: float) -> dict:
        calls.append(("search", {"lat": lat, "lng": lng}))
        return {"items": [{"sku": "bread-1", "name": "Arabic bread"}]}

    @srv.tool()
    def create_grocery_cart_with_quantities(items: list[dict], lat: float, lng: float) -> dict:
        calls.append(("cart", {"lat": lat, "lng": lng}))
        return {"cart": {"cart_id": "C42"}}

    @srv.tool()
    def cart_get_basket_price(cart_id: str) -> dict:
        return {"cart_id": cart_id, "total": total} if total is not None else {"cart_id": cart_id, "lines": 2}

    @srv.tool()
    def cart_grocery_checkout(cart_id: str, lat: float, lng: float, total_price: float = 0) -> dict:
        calls.append((CHECKOUT, {"cart_id": cart_id, "lat": lat, "lng": lng, "total_price": total_price}))
        return {"order_id": "O1"}

    return srv, calls


class NoMemory:
    def all(self, user_id):
        return []


def setup(tmp_path, **kw):
    srv, calls = fake_careem(**kw)
    store = Store(tmp_path)
    return store, calls, CareemMCPTools(store, NoMemory(), Tools(store, NoMemory()), connector=MCPConnector(url=srv))


def ctx(turn, text=""):
    return {"user_id": "um_khaled", "now": NOW, "turn": turn, "text": text}


def build_cart(tools, info=True):
    if info:
        tools.run("user_info", {}, ctx(1))
    tools.run("create_grocery_cart_with_quantities", {"items": [{"sku": "bread-1", "qty": 2}]}, ctx(1))
    tools.run("cart_get_basket_price", {"cart_id": "C42"}, ctx(1))


def test_real_connector_lists_and_calls_tools_on_mcp_2(tmp_path):
    _, calls, tools = setup(tmp_path)
    names = [s["function"]["name"] for s in tools.schemas()]
    assert "search_groceries_items" in names and CHECKOUT not in names
    assert tools.run("search_groceries_items", {"query": "خبز"}, ctx(1))["items"][0]["sku"] == "bread-1"


def test_lat_lng_from_saved_address_else_default(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREEM_LAT", "31.5")
    monkeypatch.setenv("CAREEM_LNG", "35.5")
    _, calls, tools = setup(tmp_path, address=False)
    tools.run("search_groceries_items", {"query": "milk"}, ctx(1))
    assert calls[-1] == ("search", {"lat": 31.5, "lng": 35.5})          # no saved address: env default
    _, calls, tools = setup(tmp_path / "b")
    tools.run("user_info", {}, ctx(1))
    tools.run("search_groceries_items", {"query": "milk"}, ctx(1))
    assert calls[-1] == ("search", {"lat": 31.99, "lng": 35.87})        # saved address from user_info
    tools.run("search_groceries_items", {"query": "milk", "lat": 1.0, "lng": 2.0}, ctx(1))
    assert calls[-1] == ("search", {"lat": 1.0, "lng": 2.0})            # given values are kept


def test_journey_checks_out_once_through_the_gate(tmp_path):
    _, calls, tools = setup(tmp_path)
    build_cart(tools)
    assert tools.run("request_confirmation", {"by": "user"}, ctx(1))["status"] == "waiting"
    assert "BLOCKED" in tools.run("place_order", {"confirmed_by": "user"}, ctx(1, "اه"))["error"]   # same message
    r = tools.run("place_order", {"confirmed_by": "user"}, ctx(2, "اه اطلبه"))
    assert r["status"] == "ordered"
    assert [c for c in calls if c[0] == CHECKOUT] == [
        (CHECKOUT, {"cart_id": "C42", "lat": 31.99, "lng": 35.87, "total_price": 4.25})]


def test_unknown_total_goes_to_the_family(tmp_path):
    store, calls, tools = setup(tmp_path, total=None)
    build_cart(tools)
    tools.run("request_confirmation", {"by": "user"}, ctx(1))
    r = tools.run("place_order", {"confirmed_by": "user"}, ctx(2, "اه اطلبه"))
    assert "unknown" in r["error"] and not [c for c in calls if c[0] == CHECKOUT]
    tools.run("request_confirmation", {"by": "Khaled"}, ctx(3))
    assert tools.family_checkout("um_khaled", "Khaled", NOW)["status"] == "ordered"


class FakeBedrockLLM:
    provider = "anthropic"

    def _build_inference_config(self):
        return {"maxTokens": 1024, "temperature": 0}


@pytest.mark.parametrize("provider,kept", [("anthropic", False), ("amazon", True)])
def test_mem0_temperature_is_dropped_for_claude(provider, kept):
    llm = FakeBedrockLLM()
    llm.provider = provider
    UserMemory.drop_temperature(llm)
    assert ("temperature" in llm._build_inference_config()) is kept
    assert llm._build_inference_config()["maxTokens"] == 1024


def test_mcp_all_offers_every_tool_on_the_sandbox_only(tmp_path):
    srv, _ = fake_careem()
    store = Store(tmp_path)
    tools = CareemMCPTools(store, NoMemory(), Tools(store, NoMemory()), connector=MCPConnector(url=srv), all_tools=True)
    names = [s["function"]["name"] for s in tools.schemas()]
    assert "search_groceries_items" in names and CHECKOUT not in names       # checkout stays behind the gate
    from agent.careem_mcp import is_local
    assert is_local("http://127.0.0.1:8787/mcp") and is_local("http://localhost:8787/mcp")
    assert not is_local("https://mcp.careemapis.com/mcp")

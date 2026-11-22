"""Amman mode of the local careem-mcp sandbox: the cart is what she asked for, in JOD, at an Amman address."""
import importlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "careem-mcp-sandbox"))


def load(monkeypatch):
    monkeypatch.setenv("SANDBOX_WORLD", "amman")
    import amman
    importlib.reload(amman)
    return amman


import server  # noqa: E402  (careem-mcp-sandbox/server.py)

FILES = server.load_all()


def BASE(tool, args, scenario=None):
    """Careem's own answer for the tool (what the server passes to amman.handle as the shape to fill)."""
    f = server.parse_file(FILES[tool]["path"])
    return server.render(server.select(f, args, scenario)[0]["template"], args)
HERE = {"latitude": 31.95, "longitude": 35.91}


def test_cart_is_what_she_asked_for_in_jod(monkeypatch):
    amman = load(monkeypatch)
    assert amman.ON
    u = amman.handle("user_info", {}, BASE)
    assert u["user_info"]["currency"] == "JOD" and "عمّان" in u["saved_bookmarks"][0]["subTitle"]
    s = amman.handle("search_groceries_items", {"search_terms": ["خبز", "حليب"], **HERE}, BASE)
    bread, milk = (g["items"][0] for g in s["groups"])
    assert bread["item"] == "خبز عربي صغير" and milk["item"].startswith("حليب")
    c = amman.handle("create_grocery_cart_with_quantities", {"merchant_id": 40101, **HERE, "items": [
        {"keyword": "خبز", "catalog_item_id": str(bread["id"]), "quantity": 1},
        {"keyword": "حليب", "catalog_item_id": str(milk["id"]), "quantity": 2}]}, BASE)
    assert [(i["title_localized"], i["count"]) for i in c["data"]["current_basket"]["items"]] == \
        [("خبز عربي صغير", 1), ("حليب طازج ١ لتر", 2)]
    p = amman.handle("cart_get_basket_price", {"merchant_id": 40101, **HERE}, BASE)
    assert p["price"]["price"]["total"] == round(0.35 + 2 * 1.1 + 0.75 + 0.25, 3)
    from agent.careem_mcp import CareemMCPTools
    assert CareemMCPTools.currency(p) == "JOD" and CareemMCPTools.total(p) == p["price"]["price"]["total"]


def test_checkout_once_with_the_right_price(monkeypatch):
    amman = load(monkeypatch)
    s = amman.handle("search_groceries_items", {"search_terms": ["بيض"], **HERE}, BASE)
    eggs = s["groups"][0]["items"][0]
    c = amman.handle("create_grocery_cart_with_quantities", {"merchant_id": 40101, **HERE, "items": [
        {"keyword": "بيض", "catalog_item_id": str(eggs["id"]), "quantity": 1}]}, BASE)
    bid = c["data"]["basket_id"]
    total = amman.handle("cart_get_basket_price", {"merchant_id": 40101, **HERE}, BASE)["price"]["price"]["total"]
    assert "error" in amman.handle("cart_grocery_checkout", {"basket_id": bid, "total_price": total + 5, **HERE}, BASE)
    ok = amman.handle("cart_grocery_checkout", {"basket_id": bid, "total_price": total, **HERE}, BASE)
    assert ok["currency"] == "JOD" and ok["invoice_id"].startswith("INV-")
    assert "already" in amman.handle("cart_grocery_checkout", {"basket_id": bid, "total_price": total, **HERE}, BASE)["error"]


def test_unknown_item_is_reported(monkeypatch):
    amman = load(monkeypatch)
    s = amman.handle("search_groceries_items", {"search_terms": ["unicorn"], **HERE}, BASE)
    assert s["groups"][0]["name"] == "unicorn" and s["groups"][0]["items"] == []


def test_every_amman_answer_matches_careems_output_schema(monkeypatch):
    """Live run: the app's MCP client validates answers against each tool's outputSchema; Amman answers with extra or
    missing fields (not_found, eta_minutes, upc, careem_user_id, ...) failed there and the agent said "the system is down"."""
    from jsonschema import Draft202012Validator
    amman = load(monkeypatch)
    monkeypatch.setattr(server, "amman", amman)

    def call(name, args):
        value, is_error, _ = server.call(FILES, name, args)
        assert not is_error, name
        errors = [f"{'/'.join(map(str, e.absolute_path))}: {e.message[:120]}"
                  for e in Draft202012Validator(FILES[name]["definition"]["outputSchema"]).iter_errors(value)]
        assert errors == [], f"{name}: {errors[:3]}"
        return value

    call("user_info", HERE)
    call("is_grocery_area_serviceable", HERE)
    s = call("search_groceries_items", {"search_terms": ["خبز", "unicorn"], **HERE})
    call("search_groceries_get_top_user_items", HERE)
    bread = s["groups"][0]["items"][0]
    call("create_grocery_cart_with_quantities", {"items": [{"keyword": "خبز", "catalog_item_id": str(bread["id"]),
                                                            "quantity": 2}], "merchant_id": s["merchant_id"], **HERE})
    call("search_groceries_get_top_user_items", HERE)  # now with a current basket
    call("cart_get_quik_basket", HERE)
    p = call("cart_get_basket_price", {"merchant_id": s["merchant_id"], **HERE})
    done = call("cart_grocery_checkout", {"basket_id": p["basket"]["id"], "total_price": p["price"]["price"]["total"], **HERE})
    assert done["currency"] == "JOD" and done["invoice_id"].startswith("INV-")
    call("cart_grocery_checkout", {"basket_id": p["basket"]["id"], "total_price": p["price"]["price"]["total"], **HERE})


def test_alive_check_does_not_kill_the_process():
    """On Windows os.kill(pid, 0) terminates the process; careem_mcp.py used it as a liveness check."""
    import os
    import careem_mcp
    assert careem_mcp.alive(os.getpid())  # still here afterwards, so the check didn't kill us
    assert not careem_mcp.alive(2 ** 22 + 7)

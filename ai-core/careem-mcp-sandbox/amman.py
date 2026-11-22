"""Amman mode for the local careem-mcp sandbox (SANDBOX_WORLD=amman): the grocery journey answers with what the user
actually asked for, from Jibli's Jordanian test catalog in JOD, delivered to an Amman address.

Careem's own sandbox is stateless (every cart is the same Dubai test basket in AED). For the demo we keep the same
tool names and response shapes, but these tools remember the cart:
  user_info, is_grocery_area_serviceable, search_groceries_items, search_groceries_get_top_user_items,
  create_grocery_cart_with_quantities, cart_get_quik_basket, cart_get_basket_price, cart_grocery_checkout
Everything else still comes from Careem's scenario files. Nothing is ever really ordered or charged.
"""
import json
import os
import re
import uuid
from pathlib import Path

ON = os.getenv("SANDBOX_WORLD", "dubai").lower() == "amman"
DATA = Path(os.getenv("JIBLI_CATALOG", Path(__file__).resolve().parents[1] / "data" / "catalog.json"))
MERCHANT = {"id": 40101, "name": "كريم كويك عبدون", "eta": 20}
HOME = {"id": "LOC-60001", "title": "Home", "subTitle": "جبل عمّان، الدوار الثالث، عمّان", "latitude": 31.9539,
        "longitude": 35.9106, "bookmark_id": "60001", "location_tag": "home"}
DELIVERY, SERVICE = 0.75, 0.25  # JOD
CUR = {"code": "JOD", "label": "JOD", "decimals": 3, "cents_100": False}  # same keys as Careem's basket currency
CART_CUR = {"code": "JOD", "label": "JOD", "name_localized": "دينار أردني", "position": "LEFT", "decimals": 3}  # create-cart
IMG = "https://careem-catalog-media.media.careem.com/quik/items/{}.png"
USUALS = ["milk", "bread_small", "eggs", "labneh", "tea"]
USER_ID = 900000001  # the fixture user (Careem's basket lines carry careem_user_id)
# extra words people say for the same product (Arabic dialect + English)
SYNONYMS = {"bread_small": ["خبز", "خبزه", "عيش", "bread", "pita"], "milk": ["حليب", "milk"],
            "eggs": ["بيض", "بيضات", "egg", "eggs"], "labneh": ["لبنه", "labneh"], "laban": ["لبن", "رايب", "yogurt", "laban"],
            "tomatoes": ["بندوره", "طماطم", "tomato", "tomatoes"], "cucumbers": ["خيار", "cucumber", "cucumbers"],
            "rice": ["رز", "ارز", "rice"], "sugar": ["سكر", "sugar"], "sugar_free": ["محلي", "سكرين", "sweetener"],
            "tea": ["شاي", "tea"], "coffee": ["قهوه", "coffee"], "olive_oil": ["زيت", "زيت زيتون", "olive oil", "oil"],
            "lentils": ["عدس", "lentils"], "hummus": ["حمص", "hummus"], "chicken": ["جاج", "دجاج", "chicken"],
            "dish_soap": ["جلي", "صابون", "soap"], "tissues": ["محارم", "كلينكس", "tissues"], "water": ["مي", "مياه", "ماء", "water"]}
STATE = {"cart": [], "basket_id": 7000000, "invoice": 9100, "done": {}}


def _norm(s):
    s = re.sub(r"[ً-ْـ]", "", str(s).lower())
    return re.sub(r"[أإآ]", "ا", s).replace("ة", "ه").replace("ى", "ي").strip()


def catalog():
    items = json.loads(DATA.read_text(encoding="utf-8"))
    return {c["item_id"]: {**c, "catalog_item_id": str(5000001 + i)} for i, c in enumerate(items)}


def by_catalog_id(cid):
    return next((c for c in catalog().values() if c["catalog_item_id"] == str(cid)), None)


def search(term):
    t = _norm(term)
    hits = []
    for key, c in catalog().items():
        words = [_norm(w) for w in SYNONYMS.get(key, []) + [c["name_ar"], c["name_en"], key.replace("_", " ")]]
        if any(t == w or (len(t) > 2 and (t in w or w in t)) for w in words):
            hits.append(c)
    return sorted(hits, key=lambda c: 0 if t in [_norm(w) for w in SYNONYMS.get(c["item_id"], [])] else 1)[:3]


def _item(c, template):
    """Careem's own search item (template) with our product filled in, so it matches Careem's output schema."""
    p, img = round(c["price_jod"], 3), IMG.format(c["catalog_item_id"])
    return {**template, "id": int(c["catalog_item_id"]), "item": c["name_ar"], "item_localized": c["name_ar"],
            "upc": "62" + c["catalog_item_id"], "image_url": img, "images_urls": [img], "link": img,
            "description": c["name_en"], "description_localized": c["name_ar"],
            "price": {"original": p, "original_formatted": f"{p:.2f}", "discount": 0.0, "discount_percentage": 0,
                      "discount_type": None, "total": p, "total_formatted": f"{p:.2f}", "tax_percentage": 0},
            "active": True, "is_available": True, "catalog_id": MERCHANT["id"],
            "currency": {"code": "JOD", "decimals": 3, "label": "JOD"},
            "master_product_id": c["item_id"], "is_near_expiry": False, "is_ad": False}


def _lines(kind="basket"):
    """kind=basket: cart_get_basket_price / cart_get_quik_basket lines; kind=create: create_grocery_cart current_basket."""
    out = []
    for cid, qty in STATE["cart"]:
        c = by_catalog_id(cid)
        if c:
            total = round(c["price_jod"] * qty, 3)
            line = {"item_uuid": str(uuid.uuid5(uuid.NAMESPACE_OID, f"{STATE['basket_id']}-{cid}")),
                    "catalog_item_id": c["catalog_item_id"], "title_localized": c["name_ar"], "count": qty,
                    "price": {"discount": 0, "original": total, "total": total}, "image_url": IMG.format(c["catalog_item_id"])}
            line.update({"active": True} if kind == "create" else {"comment": None, "options": None, "careem_user_id": USER_ID})
            out.append(line)
    return out


def _basket(kind="basket"):
    lines = _lines(kind)
    sub = round(sum(l["price"]["total"] for l in lines), 3)
    return {"id": STATE["basket_id"], "merchant_id": MERCHANT["id"], "domain": "shops", "business_type": "supermarkets",
            "delivery_type": "careem", "state": "active", "total_count": sum(l["count"] for l in lines),
            "count": len(lines), "version": 1, "items": lines, "missing_items": None,
            "price": {"net_total": sub, "original": sub}, "currency": CUR}


def _line(title, price, style="regular"):
    return {"label": {"title": title, "font_style": style}, "value": [{"price": price, "type": style, "font_style": style}]}


def _total():
    sub = _basket()["price"]["net_total"]
    return round(sub + DELIVERY + SERVICE, 3) if sub else 0.0


def handle(name, args, base):
    """base(name, args, scenario=None) renders Careem's own answer, used as the shape we fill in."""
    if name == "user_info":
        v = base(name, args)
        text = json.dumps(v, ensure_ascii=False).replace("Asia/Dubai", "Asia/Amman").replace('"AED"', '"JOD"')
        v = json.loads(text)
        v.setdefault("user_info", {}).update({"name": "أم خالد", "given_name": "أم خالد", "family_name": "",
                                              "locale": "ar", "currency": "JOD", "zoneinfo": "Asia/Amman"})
        v["saved_bookmarks"] = [HOME]
        v["routines"] = []
        return v
    if name == "is_grocery_area_serviceable":
        return {"page": "is_grocery_area_serviceable", "serviceable": True}
    if name in ("search_groceries_items", "search_groceries_get_top_user_items"):
        terms = args.get("search_terms") or []
        if isinstance(terms, str):
            terms = [terms]
        template = base("search_groceries_items", {"search_terms": ["milk"], "latitude": 25.0866,
                                                   "longitude": 55.1474})["groups"][0]["items"][0]
        if name == "search_groceries_get_top_user_items":
            out = {"page": "search_groceries_get_top_user_items",
                   "data": {"items": [_item(catalog()[k], template) for k in USUALS], "merchant_id": MERCHANT["id"]},
                   "source": "top_user_items", "is_personalized": True, "has_existing_items": bool(STATE["cart"])}
            if STATE["cart"]:
                out["current_basket"] = _basket()
            return out
        groups = [{"name": t, "items": [_item(c, template) for c in search(t)]} for t in terms]
        # a term with no match comes back as an empty group (Careem's schema has no separate "not found" list)
        return {"page": "grocery_items", "merchant_id": MERCHANT["id"], "domain": "quik", "merchant_name": MERCHANT["name"],
                "merchant_eta_minutes": MERCHANT["eta"], "groups": groups}
    if name == "create_grocery_cart_with_quantities":
        STATE["basket_id"] += 1
        cart, groups, missing = [], [], []
        for it in args.get("items") or []:
            c = by_catalog_id(it.get("catalog_item_id")) or (search(it.get("keyword", ""))[:1] or [None])[0]
            qty = max(1, int(it.get("quantity") or 1))
            if not c:
                missing.append(it.get("keyword"))
                continue
            cart.append((c["catalog_item_id"], qty))
            groups.append({"keyword": it.get("keyword") or c["name_ar"], "quantity": qty,
                           "items": [{"id": int(c["catalog_item_id"]), "title": c["name_ar"], "price": c["price_jod"],
                                      "image_url": IMG.format(c["catalog_item_id"]),
                                      "currency": "JOD", "secondary_info": f"JOD {c['price_jod']:.2f}",
                                      "is_available": True, "item_uuid": str(uuid.uuid4())}]})
        STATE["cart"] = cart
        b = _basket("create")
        return {"page": "create_grocery_cart_with_quantities",
                "data": {"merchant": {"id": MERCHANT["id"], "title": MERCHANT["name"], "currency": "JOD"}, "groups": groups,
                         "unavailable_keywords": missing, "basket_id": b["id"], "city_id": 1, "timezone": "Asia/Amman",
                         "payment_type": "card",
                         "current_basket": {"id": b["id"], "domain": "shops", "business_type": "QUIK",
                                            "merchant": {"id": MERCHANT["id"], "name": MERCHANT["name"]},
                                            "price": b["price"], "currency": CART_CUR, "items": b["items"]}}}
    if name == "cart_get_quik_basket":
        return {"page": "cart_get_quik_basket", "basket": _basket()}
    if name == "cart_get_basket_price":
        b, total = _basket(), _total()
        return {"page": "cart_get_basket_price",
                "merchant": {"id": MERCHANT["id"], "name": MERCHANT["name"], "name_localized": MERCHANT["name"],
                             "eta_in_minutes": MERCHANT["eta"]},
                "basket": b,
                "price": {"breakdown": [_line("Subtotal", b["price"]["net_total"]), _line("Delivery fee", DELIVERY),
                                        _line("Service fee", SERVICE), _line("Total", total, "bold")],
                          "fees": [{"type": "delivery_fee", "value": DELIVERY}, {"type": "service_fee", "value": SERVICE}],
                          "price": {"title": "Total", "total": total, "description": "Incl. VAT"}, "total_saving": 0.0},
                "payment_method": {"type": "card", "id": 4242}}
    if name == "cart_grocery_checkout":
        bid, price = args.get("basket_id"), args.get("total_price")
        if str(bid) in STATE["done"]:
            return {"page": "cart_grocery_checkout", "error": f"basket {bid} was already checked out"}
        if str(bid) != str(STATE["basket_id"]) or not STATE["cart"]:
            return {"page": "cart_grocery_checkout", "error": f"basket {bid} not found"}
        if abs(float(price or 0) - _total()) > 0.01:
            return {"page": "cart_grocery_checkout", "error": f"total_price {price} does not match the basket total {_total()}"}
        STATE["invoice"] += 1
        inv = f"INV-{STATE['invoice']}"
        STATE["done"][str(bid)] = inv
        STATE["cart"] = []
        return {"page": "cart_grocery_checkout", "invoice_id": inv, "amount": float(price), "currency": "JOD",
                "payment_type": "card",
                "checkout": {"masterInvoiceReference": inv, "childInvoices": [
                    {"serviceProvider": "quik", "clientServiceReference": str(uuid.uuid4()),
                     "invoiceReference": inv + "-1", "serviceReferenceId": STATE["invoice"]}]}}
    return None


TOOLS = {"user_info", "is_grocery_area_serviceable", "search_groceries_items", "search_groceries_get_top_user_items",
         "create_grocery_cart_with_quantities", "cart_get_quik_basket", "cart_get_basket_price", "cart_grocery_checkout"}

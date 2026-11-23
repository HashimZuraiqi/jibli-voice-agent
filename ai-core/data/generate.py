"""Generate the mock Careem Quik data and the synthetic logs. Run: .venv/bin/python data/generate.py"""
import datetime as dt
import json
import random
from pathlib import Path

import numpy as np

OUT = Path(__file__).resolve().parent
rng = random.Random(7)
np_rng = np.random.default_rng(7)

# id, English, Arabic, price (JOD), unit, category, default reorder gap (days) for cold start
CATALOG = [
    ("bread_small", "Small Arabic bread (pack)", "خبز عربي صغير", 0.35, "pack", "bakery", 2),
    ("bread_big", "Big Arabic bread (pack)", "خبز عربي كبير", 0.50, "pack", "bakery", 2),
    ("milk", "Fresh milk 1L", "حليب طازج ١ لتر", 1.10, "bottle", "dairy", 4),
    ("labneh", "Labneh 500g", "لبنة ٥٠٠ غرام", 1.60, "tub", "dairy", 6),
    ("laban", "Laban 1L", "لبن ١ لتر", 0.90, "bottle", "dairy", 5),
    ("eggs", "Eggs (30)", "بيض (٣٠ حبة)", 3.20, "tray", "dairy", 10),
    ("tomatoes", "Tomatoes 1kg", "بندورة ١ كيلو", 0.70, "kg", "vegetables", 4),
    ("cucumbers", "Cucumbers 1kg", "خيار ١ كيلو", 0.60, "kg", "vegetables", 4),
    ("rice", "Rice 5kg", "رز ٥ كيلو", 5.50, "bag", "pantry", 21),
    ("sugar", "Sugar 2kg", "سكر ٢ كيلو", 1.40, "bag", "pantry", 25),
    ("sugar_free", "Sweetener (sugar-free)", "محلي بدون سكر", 2.25, "box", "pantry", 30),
    ("tea", "Black tea 100 bags", "شاي أسود ١٠٠ كيس", 2.10, "box", "pantry", 28),
    ("coffee", "Arabic coffee with cardamom 250g", "قهوة عربية بالهيل ٢٥٠ غرام", 3.50, "pack", "pantry", 20),
    ("olive_oil", "Olive oil 1L", "زيت زيتون ١ لتر", 6.00, "bottle", "pantry", 35),
    ("lentils", "Red lentils 1kg", "عدس أحمر ١ كيلو", 1.30, "bag", "pantry", 30),
    ("hummus", "Hummus 400g", "حمص ٤٠٠ غرام", 0.85, "can", "pantry", 14),
    ("chicken", "Fresh chicken 1kg", "دجاج طازج ١ كيلو", 3.40, "kg", "meat", 7),
    ("dish_soap", "Dish soap 1L", "سائل جلي ١ لتر", 1.50, "bottle", "home", 30),
    ("tissues", "Tissues (5 boxes)", "محارم (٥ علب)", 2.40, "pack", "home", 25),
    ("water", "Water 6x1.5L", "مي ٦×١.٥ لتر", 1.20, "pack", "drinks", 5),
]

USERS = {
    "um_khaled": {
        "name": "Um Khaled", "name_ar": "أم خالد", "age": 68, "lang": "ar", "city": "Amman",
        "family": [{"name": "Khaled", "name_ar": "خالد", "relation": "son", "pays": True, "can_confirm": True},
                   {"name": "Abu Khaled", "name_ar": "أبو خالد", "relation": "husband", "pays": False, "can_confirm": False}],
        "confirm_by": "Khaled",
        # item: (median gap days, qty)
        "rhythm": {"bread_small": (2, 2), "milk": (4, 1), "labneh": (6, 1), "tomatoes": (4, 1), "eggs": (10, 1),
                   "rice": (21, 1), "sugar_free": (28, 1), "tea": (26, 1), "olive_oil": (40, 1), "water": (5, 1)},
        "usual_hour": 9, "price_sensitivity": 0.7,
    },
    "abu_sami": {
        "name": "Abu Sami", "name_ar": "أبو سامي", "age": 74, "lang": "mix", "city": "Irbid",
        "family": [{"name": "Rana", "name_ar": "رنا", "relation": "daughter", "pays": True, "can_confirm": True}],
        "confirm_by": "Rana",
        "rhythm": {"bread_big": (2, 1), "laban": (5, 1), "hummus": (10, 2), "coffee": (18, 1), "sugar": (24, 1),
                   "chicken": (7, 1), "cucumbers": (5, 1), "tissues": (25, 1)},
        "usual_hour": 17, "price_sensitivity": 0.3,
    },
    "new_user": {
        "name": "Hajjeh Fatima", "name_ar": "الحجة فاطمة", "age": 71, "lang": "ar", "city": "Zarqa",
        "family": [{"name": "Omar", "name_ar": "عمر", "relation": "grandson", "pays": True, "can_confirm": True}],
        "confirm_by": "Omar", "rhythm": {}, "usual_hour": 10, "price_sensitivity": 0.6,
    },
    "lina": {
        "name": "Lina", "name_ar": "لينا", "age": 22, "lang": "mix", "city": "Amman",
        "family": [], "confirm_by": "Lina",  # a young customer who pays and confirms herself
        "rhythm": {"water": (7, 1), "coffee": (24, 1), "hummus": (12, 1)},
        "usual_hour": 19, "price_sensitivity": 0.8,
    },
    # Hashim: the pitch opener. Works, then takes a Go from Work to the Gym every Monday around 17:00 (see SERVICES)
    "hashim": {
        "name": "Hashim", "name_ar": "هاشم", "age": 21, "lang": "ar", "city": "Amman",
        "family": [], "confirm_by": "Hashim",  # pays and confirms himself
        "rhythm": {"water": (7, 1), "coffee": (20, 1), "hummus": (10, 1)},
        "usual_hour": 20, "price_sensitivity": 0.5,
    },
}
OWN_RNG = {"lina": 22, "hashim": 21}  # users added later get their own random stream, so nobody else's data changes


def orders_for(uid, u, today, r=None):
    """Simulate 120 days of orders: each item is bought again after its gap +/- noise; same-day items share an order."""
    r = r or rng
    start = today - dt.timedelta(days=120)
    by_day = {}
    for item, (gap, qty) in u["rhythm"].items():
        # end the series so some items are due right about now
        d = start + dt.timedelta(days=r.randint(0, gap))
        while d < today - dt.timedelta(days=1):
            by_day.setdefault(d, []).append({"item_id": item, "qty": qty})
            d += dt.timedelta(days=max(1, round(gap + r.gauss(0, gap * 0.15))))
    price = {c[0]: c[3] for c in CATALOG}
    orders = []
    for i, (d, items) in enumerate(sorted(by_day.items())):
        ts = dt.datetime.combine(d, dt.time(u["usual_hour"], r.randint(0, 59)))
        orders.append({"order_id": f"{uid}-{i:03d}", "user_id": uid, "ts": ts.isoformat(timespec="minutes"),
                       "items": items, "total": round(sum(price[x["item_id"]] * x["qty"] for x in items), 2),
                       "confirmed_by": u["confirm_by"]})
    return orders


STYLES = ["gentle", "practical", "family", "short"]


def bandit_logs(n=3000):
    """Synthetic reminder logs from similar users: context -> style -> reply (1 yes, 0 no/silence)."""
    rows = []
    for _ in range(n):
        hour = rng.choice(range(8, 22))
        age = rng.randint(55, 85)
        n_due = rng.randint(1, 6)
        days_since = rng.randint(1, 20)
        is_ar = rng.random() < 0.8
        ctx = context_vector(hour, age, n_due, days_since, is_ar)
        style = rng.choice(STYLES)
        p = 0.25
        p += {"gentle": 0.20 * (age >= 65), "family": 0.25 * (age >= 70), "practical": 0.20 * (n_due >= 4),
              "short": 0.15 * (hour >= 17)}[style]
        p -= 0.10 * (days_since > 14)
        rows.append({"context": ctx, "style": style, "reward": int(rng.random() < p)})
    return rows


def context_vector(hour, age, n_due, days_since, is_ar):
    return [round(hour / 24, 3), round(age / 100, 3), round(min(n_due, 6) / 6, 3),
            round(min(days_since, 30) / 30, 3), 1.0 if is_ar else 0.0]


def uplift_logs(n=20000):
    """Synthetic offer campaign: random offers; true uplift is high for infrequent, price-sensitive users."""
    rows = []
    for _ in range(n):
        freq = np_rng.uniform(0, 30)            # orders per month
        basket = np_rng.uniform(1, 40)          # JOD
        sens = np_rng.uniform(0, 1)             # price sensitivity
        days_since = np_rng.uniform(1, 30)
        treated = int(np_rng.random() < 0.5)
        base = 0.15 + 0.4 * (freq > 6)  # frequent users buy anyway
        lift = treated * (0.25 * sens * (freq < 4) + 0.08 * (days_since > 14) - 0.02)
        rows.append({"features": [round(freq, 2), round(basket, 2), round(sens, 2), round(days_since, 1)],
                     "treatment": "offer" if treated else "control",
                     "ordered": int(np_rng.random() < min(max(base + lift, 0), 1))})
    return rows


# Saved places of the Careem test account (careem-mcp-sandbox/spec/FIXTURES.md): label -> (location id, lat, lng)
PLACES = {"Home": ("LOC-50001", 25.0866, 55.1474), "Work": ("LOC-50002", 25.2172, 55.2826),
          "Gym": ("LOC-50003", 25.0702, 55.1430), "Dubai Mall": ("LOC-poi-dubai-mall", 25.1972, 55.2796),
          "Airport T3": ("LOC-poi-dxb-t3", 25.2528, 55.3644)}
# user: rides (weekday 0=Mon, hour, from, to, product) and Box deliveries (gap days, from, to, vehicle, category)
SERVICES = {
    "um_khaled": {"rides": [(1, 9, "Home", "Dubai Mall", "Comfort"), (1, 12, "Dubai Mall", "Home", "Comfort")],
                  "box": (30, "Home", "Work", "Car", "Food, groceries")},
    "abu_sami": {"rides": [(4, 11, "Home", "Gym", "Go"), (4, 13, "Gym", "Home", "Go")],
                 "box": (14, "Work", "Home", "Motorbike", "Documents and others")},
    "new_user": {"rides": [], "box": None},
    # Lina: Go to work every weekday morning (Sun-Thu), gym after work Mon and Wed, Dubai Mall on Thursday nights
    "lina": {"rides": [(d, 8, "Home", "Work", "Go") for d in (6, 0, 1, 2, 3)]
                      + [(d, 17, "Work", "Gym", "Go") for d in (0, 2)] + [(d, 19, "Gym", "Home", "Go") for d in (0, 2)]
                      + [(3, 21, "Home", "Dubai Mall", "Comfort")],
             "box": None},
    # Hashim: Go to work every weekday morning, and after work on Monday a Go from Work to the Gym, then home
    "hashim": {"rides": [(d, 8, "Home", "Work", "Go") for d in (6, 0, 1, 2, 3)]
                       + [(0, 17, "Work", "Gym", "Go"), (0, 19, "Gym", "Home", "Go")],
              "box": None},
}


def service_history(today):
    """10 weeks of weekly rides and a few Box deliveries per user, with a little time noise."""
    rides, boxes = [], []
    start = today - dt.timedelta(days=70)
    for uid, s in SERVICES.items():
        r = random.Random(OWN_RNG[uid] + 100) if uid == "hashim" else rng  # Hashim doesn't shift anyone else's times
        for weekday, hour, a, b, product in s["rides"]:
            d = start + dt.timedelta(days=(weekday - start.weekday()) % 7)
            while d < today:
                ts = dt.datetime.combine(d, dt.time(hour, r.randint(0, 40)))
                rides.append({"user_id": uid, "ts": ts.isoformat(timespec="minutes"), "from": a, "to": b, "product": product})
                d += dt.timedelta(days=7)
        if s["box"]:
            gap, a, b, vehicle, category = s["box"]
            d = start + dt.timedelta(days=rng.randint(0, 5))
            while d < today - dt.timedelta(days=gap // 2):
                ts = dt.datetime.combine(d, dt.time(16, rng.randint(0, 59)))
                boxes.append({"user_id": uid, "ts": ts.isoformat(timespec="minutes"), "from": a, "to": b,
                              "vehicle": vehicle, "category": category})
                d += dt.timedelta(days=gap + rng.randint(-2, 2))
    return {"places": {k: {"location_id": v[0], "latitude": v[1], "longitude": v[2]} for k, v in PLACES.items()},
            "rides": sorted(rides, key=lambda r: r["ts"]), "box": sorted(boxes, key=lambda r: r["ts"])}


def main(today=None):
    today = today or dt.date.today()
    catalog = [{"item_id": i, "name_en": en, "name_ar": ar, "price_jod": p, "unit": un, "category": cat,
                "default_gap_days": g} for i, en, ar, p, un, cat, g in CATALOG]
    users = {k: {kk: vv for kk, vv in v.items() if kk != "rhythm"} for k, v in USERS.items()}
    # Lina has her own random stream so adding her leaves every other user's data unchanged
    orders = [o for uid, u in USERS.items()
              for o in orders_for(uid, u, today, random.Random(OWN_RNG[uid]) if uid in OWN_RNG else None)]
    (OUT / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=1))
    (OUT / "users.json").write_text(json.dumps(users, ensure_ascii=False, indent=1))
    (OUT / "orders.json").write_text(json.dumps(orders, ensure_ascii=False, indent=1))
    (OUT / "bandit_logs.json").write_text(json.dumps(bandit_logs()))
    (OUT / "uplift_logs.json").write_text(json.dumps(uplift_logs()))
    services = service_history(today)
    (OUT / "services.json").write_text(json.dumps(services, indent=1))
    print(f"catalog {len(catalog)} items, {len(users)} users, {len(orders)} orders, "
          f"{len(services['rides'])} rides, {len(services['box'])} Box deliveries, generated for {today}")


if __name__ == "__main__":
    main()

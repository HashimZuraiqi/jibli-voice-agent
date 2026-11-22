"""Predict: when each item runs out (Buy-it-again style, per user x item rhythm)."""
import statistics
from collections import Counter, defaultdict

from ..store import parse_ts

DUE_AT = 0.9  # due score at which we call an item "running out"


def item_history(orders):
    hist = defaultdict(list)
    for o in sorted(orders, key=lambda o: o["ts"]):
        for x in o["items"]:
            hist[x["item_id"]].append((parse_ts(o["ts"]), x["qty"]))
    return hist


def predictions(store, user_id, now):
    """Every item the user buys, with its median gap, days since last purchase and due score (high first)."""
    out = []
    for item, buys in item_history(store.orders(user_id)).items():
        dates = [d for d, _ in buys]
        c = store.catalog[item]
        if len(dates) >= 3:
            gap, source = statistics.median((b - a).days for a, b in zip(dates, dates[1:])), "own history"
        else:  # cold start for this item: category default
            gap, source = c["default_gap_days"], "category default"
        since = (now - dates[-1]).total_seconds() / 86400
        out.append({"item_id": item, "name_en": c["name_en"], "name_ar": c["name_ar"],
                    "last_bought": dates[-1].date().isoformat(), "median_gap_days": gap,
                    "days_since": round(since, 1), "due_score": round(since / max(gap, 0.5), 2),
                    "usual_qty": Counter(q for _, q in buys).most_common(1)[0][0], "source": source})
    return sorted(out, key=lambda p: -p["due_score"])


def due_items(store, user_id, now):
    return [p for p in predictions(store, user_id, now) if p["due_score"] >= DUE_AT]


def similar_user_staples(store, user_id, k=5):
    """Cold start for a new user: the items other users buy most often."""
    counts = Counter(x["item_id"] for uid in store.users if uid != user_id for o in store.orders(uid) for x in o["items"])
    return [{"item_id": i, "name_en": store.catalog[i]["name_en"], "name_ar": store.catalog[i]["name_ar"],
             "source": "similar users"} for i, _ in counts.most_common(k)]

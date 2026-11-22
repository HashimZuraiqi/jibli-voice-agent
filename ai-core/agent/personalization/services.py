"""Predict: the user's usual ride at this time of the week and their usual Box delivery (data/services.json)."""
import json
import statistics
from collections import Counter

from ..store import DATA, parse_ts

RIDE_WINDOW_H = 1.5  # a past ride counts as "usual now" if it was on the same weekday within this many hours
MIN_RIDES = 3        # ...and happened at least this many times


def load():
    p = DATA / "services.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {"places": {}, "rides": [], "box": []}


def usual_ride(data, user_id, now):
    """The trip this user takes on this weekday around this hour, if they did it at least MIN_RIDES times."""
    hour = now.hour + now.minute / 60
    near = [r for r in data["rides"] if r["user_id"] == user_id
            and parse_ts(r["ts"]).weekday() == now.weekday()
            and abs(parse_ts(r["ts"]).hour + parse_ts(r["ts"]).minute / 60 - hour) <= RIDE_WINDOW_H]
    if not near:
        return None
    (a, b, product), n = Counter((r["from"], r["to"], r["product"]) for r in near).most_common(1)[0]
    if n < MIN_RIDES:
        return None
    return {"from": a, "to": b, "product": product, "times": n, "places": {a: data["places"].get(a), b: data["places"].get(b)}}


def usual_box(data, user_id, now):
    """The Box delivery this user repeats, with how many days since the last one and whether it is due again."""
    mine = [r for r in data["box"] if r["user_id"] == user_id]
    if not mine:
        return None
    (a, b, vehicle, category), n = Counter((r["from"], r["to"], r["vehicle"], r["category"]) for r in mine).most_common(1)[0]
    dates = sorted(parse_ts(r["ts"]) for r in mine if (r["from"], r["to"]) == (a, b))
    gap = statistics.median((y - x).days for x, y in zip(dates, dates[1:])) if len(dates) >= 2 else None
    since = (now - dates[-1]).days
    return {"from": a, "to": b, "vehicle": vehicle, "category": category, "times": n, "days_since": since,
            "median_gap_days": gap, "due": bool(gap and since >= 0.9 * gap),
            "places": {a: data["places"].get(a), b: data["places"].get(b)}}

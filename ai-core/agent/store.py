"""Mock Careem data + runtime state (new orders, carts, events) kept as JSON files."""
import datetime as dt
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA, STATE = ROOT / "data", ROOT / "state"


class Store:
    def __init__(self, state_dir: Path = STATE):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.catalog = {c["item_id"]: c for c in json.loads((DATA / "catalog.json").read_text())}
        self.users = json.loads((DATA / "users.json").read_text())
        self.base_orders = json.loads((DATA / "orders.json").read_text())
        self.state = self._load()

    def _load(self):
        p = self.state_dir / "store.json"
        if p.exists():
            return json.loads(p.read_text())
        return {"orders": [], "carts": {}, "pending": {}, "events": []}

    def save(self):
        (self.state_dir / "store.json").write_text(json.dumps(self.state, ensure_ascii=False, indent=1))

    def orders(self, user_id):
        return [o for o in self.base_orders + self.state["orders"] if o["user_id"] == user_id]

    def cart(self, user_id):
        return self.state["carts"].setdefault(user_id, {})

    def cart_view(self, user_id):
        lines = [{"item_id": i, "name_en": self.catalog[i]["name_en"], "name_ar": self.catalog[i]["name_ar"], "qty": q,
                  "line_jod": round(self.catalog[i]["price_jod"] * q, 2)} for i, q in self.cart(user_id).items()]
        return {"lines": lines, "total_jod": round(sum(l["line_jod"] for l in lines), 2)}

    def log(self, user_id, kind, now, **data):
        ev = {"user_id": user_id, "kind": kind, "ts": now.isoformat(timespec="minutes"), **data}
        self.state["events"].append(ev)
        self.save()
        return ev

    def events(self, user_id, kind=None):
        return [e for e in self.state["events"] if e["user_id"] == user_id and (kind is None or e["kind"] == kind)]

    def place_order(self, user_id, confirmed_by, now):
        view = self.cart_view(user_id)
        order = {"order_id": f"{user_id}-new-{len(self.state['orders']):03d}", "user_id": user_id,
                 "ts": now.isoformat(timespec="minutes"),
                 "items": [{"item_id": l["item_id"], "qty": l["qty"]} for l in view["lines"]],
                 "total": view["total_jod"], "confirmed_by": confirmed_by}
        self.state["orders"].append(order)
        self.state["carts"][user_id] = {}
        self.state["pending"].pop(user_id, None)
        self.save()
        return order


def parse_ts(s):
    return dt.datetime.fromisoformat(s)

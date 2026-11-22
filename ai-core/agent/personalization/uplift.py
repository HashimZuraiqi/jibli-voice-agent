"""Decide: give an offer only where it changes behavior (uplift T-learner, CausalML)."""
import json
import pickle

import numpy as np
from causalml.inference.meta import BaseTClassifier
from sklearn.ensemble import GradientBoostingClassifier

from ..store import DATA, parse_ts

MIN_UPLIFT = 0.05  # predicted extra order probability needed to spend a discount
OFFER = {"discount_pct": 15, "max_jod": 1.5}


class OfferModel:
    def __init__(self, state_dir):
        path = state_dir / "uplift.pkl"
        if path.exists():
            # safe: only this app writes this file, into its own state/ folder
            self.model = pickle.loads(path.read_bytes())
        else:
            logs = json.loads((DATA / "uplift_logs.json").read_text())
            self.model = BaseTClassifier(learner=GradientBoostingClassifier(max_depth=2, n_estimators=150, random_state=7), control_name="control")
            self.model.fit(X=np.array([r["features"] for r in logs]), treatment=np.array([r["treatment"] for r in logs]),
                           y=np.array([r["ordered"] for r in logs]))
            path.write_bytes(pickle.dumps(self.model))

    @staticmethod
    def features(store, user_id, now):
        orders = store.orders(user_id)
        recent = [o for o in orders if (now - parse_ts(o["ts"])).days <= 60]
        last = max((parse_ts(o["ts"]) for o in orders), default=None)
        return [round(len(recent) / 2, 2),                                   # orders per month
                round(float(np.mean([o["total"] for o in recent])) if recent else 10.0, 2),
                store.users[user_id].get("price_sensitivity", 0.5),
                round((now - last).days if last else 30, 1)]

    def uplift(self, store, user_id, now):
        x = self.features(store, user_id, now)
        return float(self.model.predict(np.array([x])).ravel()[0]), x

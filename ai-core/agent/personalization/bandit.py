"""Decide + learn: a LinUCB contextual bandit (MABWiser) picks the reminder style; replies are the reward."""
import json
import pickle

from mabwiser.mab import MAB, LearningPolicy

from ..store import DATA

STYLES = {
    "gentle": "warm and caring, asks how they are first, then mentions the items",
    "practical": "straight to the point: lists the items running out and asks to order",
    "family": "mentions the family member who usually confirms or pays, e.g. 'shall I send it to Khaled to confirm?'",
    "short": "one short sentence, easy to answer with yes or no",
}
REWARD = {"yes": 1, "no": 0, "silence": 0}


def context_vector(hour, age, n_due, days_since, is_ar):
    # same features as data/generate.py, scaled to 0..1
    return [round(hour / 24, 3), round(age / 100, 3), round(min(n_due, 6) / 6, 3),
            round(min(days_since, 30) / 30, 3), 1.0 if is_ar else 0.0]


class ReminderBandit:
    def __init__(self, state_dir):
        self.path = state_dir / "bandit.pkl"
        if self.path.exists():
            # safe: only this app writes this file, into its own state/ folder
            self.mab = pickle.loads(self.path.read_bytes())
        else:
            # cold start: the prior comes from logged replies of similar users (offline training, Li et al. 2010)
            logs = json.loads((DATA / "bandit_logs.json").read_text(encoding="utf-8"))
            self.mab = MAB(arms=list(STYLES), learning_policy=LearningPolicy.LinUCB(alpha=0.5), seed=7)
            self.mab.fit(decisions=[r["style"] for r in logs], rewards=[r["reward"] for r in logs],
                         contexts=[r["context"] for r in logs])
            self.save()

    def save(self):
        self.path.write_bytes(pickle.dumps(self.mab))

    def choose(self, ctx):
        exp = self.mab.predict_expectations([ctx])
        style = max(exp, key=exp.get)
        return style, {k: round(float(v), 3) for k, v in exp.items()}

    def update(self, style, reply, ctx):
        self.mab.partial_fit(decisions=[style], rewards=[REWARD[reply]], contexts=[ctx])
        self.save()

"""Demo app /app/<user>: settings (who confirms), the "Why this?" data and the spoken reminder (no LLM, no AWS)."""
import datetime as dt
import importlib

import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("CAREEM_PROVIDER", "mock")
    monkeypatch.setenv("MEMORY_PROVIDER", "agentcore")
    monkeypatch.setenv("AGENTCORE_MEMORY_ID", "JibliMemory-test123456")
    monkeypatch.setenv("TTS_PROVIDER", "browser")
    from fastapi.testclient import TestClient
    import web.app as app
    importlib.reload(app)
    from agent.store import Store
    app.S["store"] = store = Store(tmp_path)
    app.S["brain"].store = store
    c = TestClient(app.app)
    c.app_module, c.store = app, store
    return c


def test_app_page_served(client):
    assert "جيبلي" in client.get("/app/um_khaled").text
    assert client.get("/app/nobody").status_code == 404
    assert client.get("/voice/um_khaled").status_code == 200 and client.get("/family/um_khaled").status_code == 200


def test_settings_default_save_and_reject(client):
    s = client.get("/api/settings/um_khaled").json()
    assert s["confirm_mode"] == "either" and s["confirmer"] == "Khaled"
    assert s["limits"]["quiet_hours"] == [22, 8] and s["limits"]["reminders_per_day"] == 1
    assert client.post("/api/settings/um_khaled", json={"confirm_mode": "family"}).json()["confirm_mode"] == "family"
    assert client.store.state["settings"]["um_khaled"]["confirm_mode"] == "family"
    assert client.get("/api/family-view/um_khaled").json()["confirm_mode"] == "family"
    assert client.post("/api/settings/um_khaled", json={"confirm_mode": "anyone"}).status_code == 400
    assert client.post("/api/settings/nobody", json={"confirm_mode": "self"}).status_code == 404


def test_confirm_mode_reaches_only_the_confirm_rules(client):
    brain = client.app_module.S["brain"]
    now = dt.datetime(2026, 11, 22, 10, 0)
    advice = client.app_module.S["layer"].advise("um_khaled", now)
    base = brain.system("um_khaled", now, [], advice)
    client.post("/api/settings/um_khaled", json={"confirm_mode": "self"})
    assert "chose to confirm her own orders" in brain.system("um_khaled", now, [], advice)
    client.post("/api/settings/um_khaled", json={"confirm_mode": "family"})
    assert "must approve and pay" in brain.system("um_khaled", now, [], advice)
    client.post("/api/settings/um_khaled", json={"confirm_mode": "either"})
    assert brain.system("um_khaled", now, [], advice) == base


def test_why_has_history_scores_decision_and_spoken_text(client, monkeypatch):
    app = client.app_module
    monkeypatch.setattr(app.S["brain"], "reminder",
                        lambda uid, now: {"reply": "يا خالتي الحليب قرّب يخلص", "advice": {"style": "family"}})
    client.post("/api/reminder", json={"user_id": "um_khaled", "time": "10:00"})
    w = client.get("/api/why/um_khaled").json()
    milk = next(i for i in w["items"] if i["item_id"] == "milk")
    assert milk["dates"] and milk["median_gap_days"] > 0 and "due_score" in milk
    assert w["advice"]["style"] and "offer_decision" in w["advice"]
    assert w["spoken"]["text"] == "يا خالتي الحليب قرّب يخلص" and w["spoken"]["style"] == "family"
    assert w["usual_hour"] == 9

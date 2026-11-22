"""Voice page, /api/voice, /api/say, family page and /api/family-view (no LLM, no AWS, no microphone)."""
import importlib
import os
import sys
import types

import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # set before importing the app (load_dotenv never overrides variables that are already set)
    monkeypatch.setenv("CAREEM_PROVIDER", "mock")
    monkeypatch.setenv("MEMORY_PROVIDER", "agentcore")
    monkeypatch.setenv("AGENTCORE_MEMORY_ID", "JibliMemory-test123456")
    monkeypatch.setenv("TTS_PROVIDER", "browser")
    fake = types.ModuleType("fake_speech")
    fake.stt = lambda audio_bytes: " ابعتلي خبز وحليب "
    fake.tts = lambda text: b"RIFF0000WAVEfmt "
    monkeypatch.setitem(sys.modules, "fake_speech", fake)
    from fastapi.testclient import TestClient
    import web.app as app
    importlib.reload(app)
    from agent.store import Store
    app.S["store"] = store = Store(tmp_path)
    seen = []

    def handle(user_id, text, now):
        seen.append(text)
        return {"reply": "تمام يا خالتي", "steps": []}
    monkeypatch.setattr(app.S["brain"], "handle", handle)
    c = TestClient(app.app)
    c.app_module, c.store, c.seen = app, store, seen
    return c


def test_pages_served(client):
    assert "اضغطي واحكي" in client.get("/voice/um_khaled").text
    assert "موافقة" in client.get("/family/um_khaled").text
    assert client.get("/voice/nobody").status_code == 404


def test_voice_transcribes_and_returns_the_text(client, monkeypatch):
    monkeypatch.setenv("STT_PROVIDER", "func")
    monkeypatch.setenv("STT_FUNC", "fake_speech:stt")
    r = client.post("/api/voice?user_id=um_khaled", content=b"\x1aE\xdf\xa3fake-webm",
                    headers={"Content-Type": "audio/webm"}).json()
    assert r["transcript"] == "ابعتلي خبز وحليب" and r["reply"] == "تمام يا خالتي"
    assert client.seen == ["ابعتلي خبز وحليب"]
    assert r["audio_b64"] is None  # browser speaks it


def test_voice_with_tts_function(client, monkeypatch):
    monkeypatch.setenv("STT_PROVIDER", "func")
    monkeypatch.setenv("STT_FUNC", "fake_speech:stt")
    monkeypatch.setenv("TTS_PROVIDER", "func")
    monkeypatch.setenv("TTS_FUNC", "fake_speech:tts")
    r = client.post("/api/voice?user_id=um_khaled", content=b"audio", headers={"Content-Type": "audio/webm"}).json()
    assert r["audio_b64"] and r["audio_mime"] == "audio/wav"


def test_no_stt_says_type_instead(client, monkeypatch):
    monkeypatch.setenv("STT_PROVIDER", "none")
    r = client.post("/api/voice?user_id=um_khaled", content=b"audio", headers={"Content-Type": "audio/webm"})
    assert r.status_code == 503 and "type" in r.json()["detail"]


def test_typed_text_goes_to_the_same_brain(client):
    r = client.post("/api/say", json={"user_id": "um_khaled", "text": "اه"}).json()
    assert r["reply"] == "تمام يا خالتي" and client.seen == ["اه"]


def test_family_view_shows_what_is_waiting(client):
    assert client.get("/api/family-view/um_khaled").json()["waiting"] is False
    client.store.cart("um_khaled")["milk"] = 2
    client.store.state["pending"]["um_khaled"] = {"by": "Um Khaled", "ts": "2026-11-22T12:00", "turn": 1,
                                                  "cart": client.store.cart_view("um_khaled")}
    v = client.get("/api/family-view/um_khaled").json()
    assert v["waiting"] and v["asked_user"] and v["currency"] == "JOD" and v["items"][0]["qty"] == 2
    # Careem sandbox basket (CAREEM_PROVIDER=mcp)
    client.store.state["pending"]["um_khaled"] = {"by": "Khaled", "ts": "t", "turn": 1, "cart": {
        "basket": {"items": [{"title_localized": "Sourdough Loaf", "count": 1, "price": {"total": 12.0}}]},
        "price": {"total": 45.5}, "currency": "AED"}}
    v = client.get("/api/family-view/um_khaled").json()
    assert not v["asked_user"] and v["total"] == 45.5 and v["items"][0]["name"] == "Sourdough Loaf"


def test_family_view_gives_arabic_names(client):
    """Live run: the pages said "بنستنى Khaled يوافق" and spoke "وافق Khaled"; names are stored in English."""
    v = client.get("/api/family-view/um_khaled").json()
    assert v["names"]["Khaled"] == "خالد" and v["names"]["Um Khaled"] == "أم خالد" and v["confirmer"] == "Khaled"

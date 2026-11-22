"""Voice page adapter for the local Leva-TTS server (stt/leva_server.py): tts(text) -> WAV bytes.

ai-core/.env:  TTS_PROVIDER=func   TTS_FUNC=stt.leva:tts   (optional LEVA_URL, default http://127.0.0.1:8790)
Standard library only, so it runs in the app's venv. If the server is down, the voice page falls back to the
browser's voice automatically.
"""
import json
import os
import urllib.request


def tts(text: str) -> bytes:
    url = os.getenv("LEVA_URL", "http://127.0.0.1:8790").rstrip("/") + "/tts"
    req = urllib.request.Request(url, data=json.dumps({"text": text}, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=float(os.getenv("LEVA_TIMEOUT", "30"))) as r:
        return r.read()

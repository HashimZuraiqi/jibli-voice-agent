"""Leva-TTS (Levantine Arabic) as a tiny local voice server, in its OWN venv so torch 2.3 / coqui-tts can't break
the app's packages. The app calls it over HTTP through stt/leva.py.

Setup (once, Windows PowerShell; Python 3.10 recommended):
    py -3.10 -m venv ..\\leva-venv
    ..\\leva-venv\\Scripts\\pip install torch==2.3.0 torchaudio==2.3.0 --index-url https://download.pytorch.org/whl/cpu
        (NVIDIA GPU: use .../whl/cu121 instead of /cpu)
    ..\\leva-venv\\Scripts\\pip install leva-tts soundfile
    + espeak-ng and ffmpeg on the PATH
Run (keep this terminal open during the demo):
    ..\\leva-venv\\Scripts\\python stt\\leva_server.py            # http://127.0.0.1:8790
Then in ai-core/.env:  TTS_PROVIDER=func   TTS_FUNC=stt.leva:tts

Model: https://huggingface.co/mohammedaly22/leva-tts (fine-tuned XTTS-v2). Weights are NON-COMMERCIAL (Coqui CPML /
CC-BY-NC): fine for the hackathon demo, not for a shipped product.
Env: LEVA_SPEAKER (one of the 10 built-in speakers, default Badr), LEVA_DEVICE (cuda / cpu, default auto),
     LEVA_PORT (8790), LEVA_TEMPERATURE (0.65), LEVA_SPEED (1.0).
"""
import io
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import soundfile as sf
from leva_tts import SPEAKERS, LevaTTS

SPEAKER = os.getenv("LEVA_SPEAKER", "Badr")
print(f"Loading Leva-TTS (speakers: {', '.join(SPEAKERS)}) ...", flush=True)
t = time.time()
TTS = LevaTTS(device=os.getenv("LEVA_DEVICE") or None, preprocess_text=True, verbose=False)
TTS.synthesize("هلا", speaker=SPEAKER)  # warm-up, so the first real reply isn't the slow one
print(f"Ready in {time.time() - t:.0f} s on http://127.0.0.1:{os.getenv('LEVA_PORT', '8790')}  (speaker {SPEAKER})", flush=True)


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/tts":
            return self.send_error(404)
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        text, speaker = (body.get("text") or "").strip(), body.get("speaker") or SPEAKER
        if not text:
            return self.send_error(400, "empty text")
        if speaker not in SPEAKERS:
            return self.send_error(400, f"speaker must be one of {list(SPEAKERS)}")
        t = time.time()
        wav, sr = TTS.synthesize(text[:600], speaker=speaker, temperature=float(os.getenv("LEVA_TEMPERATURE", "0.65")),
                                 speed=float(os.getenv("LEVA_SPEED", "1.0")))
        buf = io.BytesIO()
        sf.write(buf, wav, sr, format="WAV")
        data = buf.getvalue()
        print(f"{time.time() - t:.1f} s  {len(text)} chars  {speaker}", flush=True)
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):  # health check: GET /  -> speakers
        payload = json.dumps({"ok": True, "speaker": SPEAKER, "speakers": list(SPEAKERS)}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *a):
        pass


ThreadingHTTPServer(("127.0.0.1", int(os.getenv("LEVA_PORT", "8790"))), Handler).serve_forever()

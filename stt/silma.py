"""SILMA TTS adapter for the voice page: tts(text) -> WAV bytes.

Use it with (ai-core/.env):  TTS_PROVIDER=func   TTS_FUNC=stt.silma:tts
Install in the SAME venv the app runs in only after testing it separately:  pip install silma-tts  (needs ffmpeg).
Model: https://huggingface.co/silma-ai/silma-tts (F5-TTS, 150M, Arabic MSA + English, Apache-2.0).

Voice: SILMA clones the voice of a short reference clip (<8 s) plus its transcript.
  SILMA_REF_WAV=path/to/voice.wav  SILMA_REF_TEXT="what is said in it"   (default: SILMA's own Arabic sample)
Only clone a real person's voice with their documented consent, and say the audio is AI-generated.
"""
import io
import os
import wave
from pathlib import Path

_model = {}
SAMPLE_TEXT = "ويدقق النظر في القرآن الكريم وسائر الكتب السماوية ويتبع مسالك الرسل العظام عليهم الصلاة والسلام."


def _reference():
    wav = os.getenv("SILMA_REF_WAV")
    if wav:
        return wav, os.getenv("SILMA_REF_TEXT") or None  # None = SILMA transcribes it itself
    import silma_tts
    sample = Path(silma_tts.__file__).parent / "infer" / "ref_audio_samples" / "ar.ref.24k.wav"
    return str(sample), SAMPLE_TEXT


def _to_wav_bytes(samples, sr):
    import numpy as np
    pcm = (np.clip(np.asarray(samples, dtype="float32"), -1, 1) * 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def tts(text: str) -> bytes:
    if "m" not in _model:
        from silma_tts.api import SilmaTTS
        _model["m"] = SilmaTTS()
    ref_file, ref_text = _reference()
    wav, sr, _ = _model["m"].infer(ref_file=ref_file, ref_text=ref_text, gen_text=text, seed=None,
                                   speed=float(os.getenv("SILMA_SPEED", "1")))
    return _to_wav_bytes(wav, sr)

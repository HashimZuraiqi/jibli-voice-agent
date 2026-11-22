"""Speech in and out for the voice page. Swappable from .env so Anas's functions drop in without code changes.

STT_PROVIDER  = whisper (default: local openai-whisper, WHISPER_MODEL=small, Arabic)
              | func    (STT_FUNC=module:function, e.g. stt.anas:stt -> stt(audio_bytes) -> text;
                         a second `mime` parameter is passed if the function takes one)
              | browser (the page uses the browser's own speech recognition, Edge/Chrome, ar-JO; no install,
                         needs internet; the words go to /api/say like typing)
              | none    (the page asks the user to type)
TTS_PROVIDER  = browser (default: the page speaks with the browser's own Arabic voice)
              | polly   (Amazon Polly, POLLY_VOICE=Hala, neural, ar-AE; same AWS keys as Bedrock)
              | func    (TTS_FUNC=module:function, e.g. stt.anas:tts -> tts(text) -> audio_bytes or (bytes, mime))
Modules are found from ai-core/ or the repo root (so the root stt/ folder works).

Privacy: audio is only used to transcribe. It is never stored: kept in memory, or in a temp file deleted right after.
"""
import importlib
import inspect
import os
import sys
import tempfile
from pathlib import Path

for _p in (Path(__file__).resolve().parents[1], Path(__file__).resolve().parents[2]):  # ai-core/, repo root
    if str(_p) not in sys.path:
        sys.path.append(str(_p))

_whisper = {}


class NoSTT(RuntimeError):
    pass


def _load(spec):
    module, _, fn = spec.partition(":")
    if not module or not fn:
        raise RuntimeError(f"expected module:function, got {spec!r}")
    return getattr(importlib.import_module(module), fn)


def transcribe(audio: bytes, mime: str = "audio/webm") -> str:
    provider = os.getenv("STT_PROVIDER", "whisper").lower()
    if not audio:
        raise NoSTT("empty recording")
    if provider == "browser":
        raise NoSTT("speech-to-text runs in the browser (STT_PROVIDER=browser): the page sends the words, not audio")
    if provider == "none":
        raise NoSTT("speech-to-text is off (STT_PROVIDER=none): type the message instead")
    if provider == "func":
        fn = _load(os.getenv("STT_FUNC", ""))
        try:
            takes_mime = len(inspect.signature(fn).parameters) >= 2
        except (TypeError, ValueError):
            takes_mime = False
        return str(fn(audio, mime) if takes_mime else fn(audio)).strip()
    try:
        import whisper  # openai-whisper, needs ffmpeg on the PATH
    except ImportError as e:
        raise NoSTT("openai-whisper is not installed (pip install openai-whisper, plus ffmpeg), "
                    "or set STT_PROVIDER=func / none") from e
    name = os.getenv("WHISPER_MODEL", "small")
    if name not in _whisper:
        _whisper[name] = whisper.load_model(name)
    ext = {"audio/webm": ".webm", "audio/ogg": ".ogg", "audio/wav": ".wav", "audio/mp4": ".m4a",
           "audio/mpeg": ".mp3"}.get(mime.split(";")[0].strip(), ".webm")
    fd, path = tempfile.mkstemp(suffix=ext)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(audio)
        out = _whisper[name].transcribe(path, language=os.getenv("WHISPER_LANGUAGE", "ar"), fp16=False)
        return (out.get("text") or "").strip()
    finally:
        os.remove(path)  # the recording is deleted right after transcription


def speak(text: str):
    """Returns (audio_bytes, mime), or None when the browser should speak the text itself."""
    provider = os.getenv("TTS_PROVIDER", "browser").lower()
    if not text or provider == "browser":
        return None
    if provider == "func":
        out = _load(os.getenv("TTS_FUNC", ""))(text)
        if isinstance(out, tuple):
            return out
        return out, ("audio/mpeg" if out[:3] == b"ID3" or out[:2] == b"\xff\xfb" else "audio/wav")
    if provider == "polly":
        import boto3
        r = boto3.session.Session().client("polly", region_name=os.getenv("AWS_REGION", "us-east-1")).synthesize_speech(
            Text=text[:2900], OutputFormat="mp3", VoiceId=os.getenv("POLLY_VOICE", "Hala"),
            Engine=os.getenv("POLLY_ENGINE", "neural"), LanguageCode=os.getenv("POLLY_LANGUAGE", "ar-AE"))
        return r["AudioStream"].read(), "audio/mpeg"
    raise RuntimeError(f"unknown TTS_PROVIDER {provider!r}")

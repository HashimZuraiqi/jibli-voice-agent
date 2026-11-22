"""Compare text-to-speech voices on the same Jordanian-Arabic replies, timed on THIS laptop.

    .venv/bin/python scripts/tts_compare.py                 # Amazon Polly voices (needs the AWS keys in .env)
    .venv/bin/python scripts/tts_compare.py --silma         # + SILMA (pip install silma-tts, ffmpeg; first run downloads it)

Writes audio files to ai-core/tts_samples/ (git-ignored) and prints seconds per sentence. Listen and pick by ear:
does the dialect sound natural, and is it fast enough that grandma isn't waiting?
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT.parent)]
from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

SENTENCES = [
    "هلا يا خالتي، السلة فيها حليب اثنين، وكرتونة بيض، ورغيف خبز، والمجموع ٤٥ درهم ونص. أبعتها؟",
    "تمام يا خالتي، الطلب انبعت، وبيوصلك بعد ربع ساعة.",
    "يا خالتي، الحليب والخبز قربوا يخلصوا. بدك نفس الطلبية زي كل مرة؟",
]
OUT = ROOT / "tts_samples"
OUT.mkdir(exist_ok=True)


def polly(voice, engine, lang):
    import boto3
    client = boto3.session.Session().client("polly", region_name=os.getenv("AWS_REGION", "us-east-1"))

    def say(text):
        return client.synthesize_speech(Text=text, OutputFormat="mp3", VoiceId=voice, Engine=engine,
                                        LanguageCode=lang)["AudioStream"].read(), "mp3"
    return say


def silma():
    from stt.silma import tts

    def say(text):
        return tts(text), "wav"
    return say


voices = {"polly-Hala-neural": lambda: polly("Hala", "neural", "ar-AE"),
          "polly-Zayd-neural": lambda: polly("Zayd", "neural", "ar-AE"),
          "polly-Zeina-standard": lambda: polly("Zeina", "standard", "arb")}
if "--silma" in sys.argv:
    voices["silma"] = silma

for name, make in voices.items():
    try:
        say = make()
        times = []
        for i, text in enumerate(SENTENCES, 1):
            t = time.time()
            audio, ext = say(text)
            times.append(time.time() - t)
            (OUT / f"{name}-{i}.{ext}").write_bytes(audio)
        print(f"{name:22s} seconds per sentence: {', '.join(f'{x:.1f}' for x in times)}"
              + ("   (first one includes loading the model)" if name == "silma" else ""))
    except Exception as e:
        print(f"{name:22s} FAILED: {type(e).__name__}: {str(e)[:160]}")
print(f"\nListen to the files in {OUT}")

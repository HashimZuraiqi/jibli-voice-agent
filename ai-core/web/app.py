"""Demo server: .venv/bin/python -m uvicorn web.app:app --port 8000  then open http://127.0.0.1:8000"""
import datetime as dt
import os
import shutil
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

from agent.brain import Brain  # noqa: E402  (needs the env loaded first)
from agent.llm import LLM, QuotaExceeded  # noqa: E402
from agent.memory import make_memory  # noqa: E402
from agent.personalization.layer import PersonalizationLayer  # noqa: E402
from agent.store import STATE, Store  # noqa: E402
from agent.careem_mcp import CareemMCPTools, make_tools  # noqa: E402
from agent import voice  # noqa: E402

app = FastAPI(title="Voice agent: LLM brain + personalization")
S = {}


def build():
    store = Store()
    llm = LLM()
    memory = S.get("memory") or make_memory(STATE, llm.models)  # Mem0's Qdrant keeps a file lock, so reuse it
    layer = PersonalizationLayer(store)
    tools = make_tools(store, memory, layer.services["places"])  # CAREEM_PROVIDER: mock, mcp or mcp-all
    S.update(store=store, memory=memory, layer=layer, brain=Brain(store, memory, layer, tools, llm))


build()


def now_from(t):
    """Demo clock: optional HH:MM override for today, to show quiet hours etc."""
    n = dt.datetime.now().replace(second=0, microsecond=0)
    if t and "T" in t:  # full date and time, e.g. 2026-11-24T09:10
        return dt.datetime.fromisoformat(t)
    if t:
        h, m = (int(x) for x in t.split(":"))
        n = n.replace(hour=h, minute=m)
    return n


def check_user(uid):
    if uid not in S["store"].users:
        raise HTTPException(404, f"unknown user {uid}")


@app.exception_handler(QuotaExceeded)
async def quota(_, e):
    return JSONResponse({"error": str(e)}, status_code=429)


@app.exception_handler(RuntimeError)
async def llm_failed(_, e):  # all models failed (bad key, provider down): show it on the page
    return JSONResponse({"error": f"LLM unavailable: {str(e)[:300]}. Check the AWS credentials (or OPENROUTER_API_KEY) in .env."}, status_code=502)


class Msg(BaseModel):
    user_id: str
    text: str = ""
    time: str | None = None


class Feedback(BaseModel):
    user_id: str
    reply: str  # yes / no / silence
    time: str | None = None


class Family(BaseModel):
    user_id: str
    approve: bool
    time: str | None = None


class Forget(BaseModel):
    user_id: str
    memory_id: str = "all"


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/api/users")
def users():
    return S["store"].users


@app.get("/api/state/{user_id}")
def state(user_id: str, time: str | None = None):
    check_user(user_id)
    st, now = S["store"], now_from(time)
    S["memory"].seed(user_id)
    snap = S["layer"].snapshot(user_id, now)
    return {"now": now.isoformat(timespec="minutes"), "user": st.users[user_id], "memory": S["memory"].all(user_id),
            "predictions": snap["predictions"][:8], "advice": snap["advice"], "cart": st.cart_view(user_id),
            "pending": st.state["pending"].get(user_id), "orders": st.orders(user_id)[-3:][::-1],
            "service_orders": [o for o in st.state.get("service_orders", []) if o["user_id"] == user_id][-5:][::-1],
            "events": st.events(user_id)[-12:][::-1], "llm_calls": S["brain"].llm.calls,
            "careem_provider": ("Careem MCP, all services" if hasattr(S["brain"].tools, "execute_pending")
                                else "Careem MCP, groceries" if hasattr(S["brain"].tools, "family_checkout") else "mock"),
            "memory_provider": "AgentCore Memory" if type(S["memory"]).__name__ == "AgentCoreMemory" else "Mem0"}


@app.post("/api/chat")
def chat(m: Msg):
    check_user(m.user_id)
    if not m.text.strip():
        raise HTTPException(400, "empty message")
    return S["brain"].handle(m.user_id, m.text.strip()[:1000], now_from(m.time))


@app.post("/api/reminder")
def reminder(m: Msg):
    check_user(m.user_id)
    return S["brain"].reminder(m.user_id, now_from(m.time))


@app.post("/api/feedback")
def feedback(f: Feedback):
    check_user(f.user_id)
    if f.reply not in ("yes", "no", "silence"):
        raise HTTPException(400, "reply must be yes, no or silence")
    ev = S["layer"].feedback(f.user_id, f.reply, now_from(f.time))
    return {"rewarded": ev}


@app.post("/api/family")
def family(f: Family):
    check_user(f.user_id)
    by = S["store"].users[f.user_id]["confirm_by"]
    return S["brain"].family_decision(f.user_id, by, f.approve, now_from(f.time))


@app.post("/api/forget")
def forget(f: Forget):
    check_user(f.user_id)
    return {"deleted": S["memory"].forget(f.user_id, None if f.memory_id == "all" else f.memory_id)}


@app.post("/api/reset")
def reset():
    """Forget all learning and orders made in the demo (keeps the mock data)."""
    for uid in S["store"].users:
        S["memory"].forget(uid)
    for name in ("store.json", "bandit.pkl", "uplift.pkl"):
        (STATE / name).unlink(missing_ok=True)
    build()
    return {"status": "reset"}


# ---------------------------------------------------------------- voice page (elder) + family page (Faris)

@app.get("/voice/{user_id}")
def voice_page(user_id: str):
    check_user(user_id)
    return FileResponse(ROOT / "web" / "voice.html")


@app.get("/family/{user_id}")
def family_page(user_id: str):
    check_user(user_id)
    return FileResponse(ROOT / "web" / "family.html")


TOOL_STATUS = {  # what grandma sees while the agent works, in Jordanian Arabic
    "user_info": "عم بجيب عنوانك…",
    "is_grocery_area_serviceable": "عم بتأكد إنه كريم بيوصل لعندك…",
    "search_groceries_get_top_user_items": "عم بشوف أغراضك المعتادة…",
    "search_groceries_get_all_deals": "عم بدوّر على العروض…",
    "create_grocery_cart_with_quantities": "عم بحط الأغراض بالسلة…",
    "cart_get_quik_basket": "عم بشوف السلة…",
    "cart_get_basket_price": "عم بحسب المجموع مع التوصيل…",
    "cart_get_checkout_promos": "عم بدوّر على خصم…",
    "request_confirmation": "تقريباً جاهز…",
    "place_order": "عم بطلبلك هلق…",
    "memory_list": "عم بتذكّر شو بعرف عنك…",
    "memory_forget": "عم بمسح…",
    "search_catalog": "عم بدوّر على الأغراض…", "usual_basket": "عم بشوف أغراضك المعتادة…",
    "add_to_cart": "عم بحط الأغراض بالسلة…", "view_cart": "عم بشوف السلة…",
}


def status_text(p):
    if not p:
        return "لحظة…"
    key, d = p["key"], p.get("detail", {})
    if key == "remember":
        return "عم بتذكّر شو بتحبي…"
    if key == "think":
        return "عم بفكّر…" if d.get("round", 0) == 0 else "شوي كمان…"
    if key == "reply":
        return "عم بكتبلك الرد…"
    if key == "consent":
        return "عم بفهم ردّك…"
    if key == "voice":
        return "عم بجهّز الصوت…"
    if key == "tool":
        name, args = d.get("name", ""), d.get("args") or {}
        if name == "search_groceries_items":
            terms = args.get("search_terms") or []
            terms = [terms] if isinstance(terms, str) else terms
            return f"عم بدوّر على {'، '.join(map(str, terms[:4]))} بكريم…" if terms else "عم بدوّر على الأغراض بكريم…"
        return TOOL_STATUS.get(name, "عم بشتغل على طلبك…")
    return "لحظة…"


@app.get("/api/progress/{user_id}")
def progress(user_id: str):
    """What the agent is doing right now (the voice page polls this while waiting for a reply)."""
    check_user(user_id)
    p = S["brain"].live.get(user_id)
    return {"n": p["n"] if p else 0, "key": p["key"] if p else None, "text": status_text(p)}


def spoken(reply, user_id=None):
    """Text-to-speech for a reply; never fails the request (the page falls back to the browser's voice)."""
    if user_id and os.getenv("TTS_PROVIDER", "browser").lower() != "browser":
        S["brain"].progress(user_id, "voice")
    try:
        out = voice.speak(reply)
    except Exception as e:  # e.g. Polly not allowed or offline
        print(f"[voice] TTS failed, browser will speak: {type(e).__name__}: {e}")
        return None, None
    if not out:
        return None, None
    import base64
    return base64.b64encode(out[0]).decode(), out[1]


@app.get("/api/voice-config")
def voice_config():
    """Tells the voice page how to listen: browser (its own speech recognition) or server (/api/voice)."""
    return {"stt": "browser" if os.getenv("STT_PROVIDER", "whisper").lower() == "browser" else "server",
            "tts": os.getenv("TTS_PROVIDER", "browser").lower()}


@app.post("/api/voice")
async def voice_message(request: Request, user_id: str, time: str | None = None):
    """Body = the recorded audio (any browser format). Audio -> STT -> brain -> TTS. The audio is never stored."""
    check_user(user_id)
    audio = await request.body()
    try:
        text = voice.transcribe(audio, request.headers.get("content-type", "audio/webm"))
    except voice.NoSTT as e:
        raise HTTPException(503, str(e))
    if not text:
        raise HTTPException(422, "I couldn't hear anything, please try again")
    out = S["brain"].handle(user_id, text[:1000], now_from(time))
    audio_b64, mime = spoken(out["reply"], user_id)
    return {"transcript": text, "reply": out["reply"], "audio_b64": audio_b64, "audio_mime": mime,
            "waiting": family_view(user_id)}


class Say(BaseModel):
    user_id: str
    text: str
    time: str | None = None


@app.post("/api/say")
def say(m: Say):
    """Typed text or a tapped yes / no button on the voice page: same brain, spoken reply."""
    check_user(m.user_id)
    if not m.text.strip():
        raise HTTPException(400, "empty message")
    out = S["brain"].handle(m.user_id, m.text.strip()[:1000], now_from(m.time))
    audio_b64, mime = spoken(out["reply"], m.user_id)
    return {"transcript": m.text, "reply": out["reply"], "audio_b64": audio_b64, "audio_mime": mime,
            "waiting": family_view(m.user_id)}


def _items(cart):
    """Item lines from whatever the path stored: a Careem basket answer, or the mock cart view."""
    if not isinstance(cart, dict):
        return []
    if cart.get("lines"):  # mock cart_view
        return [{"name": l["name_ar"], "qty": l["qty"], "price": l["line_jod"]} for l in cart["lines"]]
    basket = cart.get("basket") if isinstance(cart.get("basket"), dict) else cart
    return [{"name": i.get("title_localized") or i.get("title") or i.get("name") or "?",
             "qty": i.get("count") or i.get("quantity") or 1,
             "price": (i.get("price") or {}).get("total") if isinstance(i.get("price"), dict) else i.get("price")}
            for i in (basket.get("items") or []) if isinstance(i, dict)]


@app.get("/api/family-view/{user_id}")
def family_view(user_id: str):
    """What the family page shows: the order waiting for approval (any Careem path), or the last order."""
    check_user(user_id)
    st, u = S["store"], S["store"].users[user_id]
    p = st.state["pending"].get(user_id)
    # Arabic names for the pages (confirm_by, pending "by", last order "by" are stored in English)
    names = {u["name"]: u.get("name_ar", u["name"]), **{f["name"]: f.get("name_ar", f["name"]) for f in u.get("family", [])}}
    view = {"user": {"name": u["name"], "name_ar": u.get("name_ar", u["name"])}, "confirmer": u.get("confirm_by"),
            "names": names, "waiting": False}
    if p:
        cart = p.get("cart")
        if p.get("tool"):  # mcp-all: careem.py stored the exact checkout
            total, currency = p.get("total"), p.get("currency")
        elif isinstance(cart, dict) and "total_jod" in cart:  # mock
            total, currency = cart["total_jod"], "JOD"
        else:  # mcp: Careem basket answer
            total, currency = CareemMCPTools.total(cart or {}), CareemMCPTools.currency(cart or {})
        view.update(waiting=True, asked=p["by"], asked_user=p["by"] == u["name"], since=p.get("ts"),
                    items=_items(cart), total=total, currency=currency, summary=p.get("summary"))
    done = [e for e in st.events(user_id) if e["kind"] in ("careem_order", "confirmation_declined")]
    service = [o for o in st.state.get("service_orders", []) if o["user_id"] == user_id]
    local = st.orders(user_id)
    last = max([(e["ts"], e) for e in done] + [(o["ts"], o) for o in service] + [(o["ts"], o) for o in local[-1:]],
               key=lambda x: x[0], default=(None, None))[1]
    view["last"] = last
    return view

"""Demo server: .venv/bin/python -m uvicorn web.app:app --port 8000  then open http://127.0.0.1:8000"""
import datetime as dt
import os
import shutil
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

from agent.brain import Brain  # noqa: E402  (needs the env loaded first)
from agent.llm import LLM, QuotaExceeded  # noqa: E402
from agent.memory import UserMemory  # noqa: E402
from agent.personalization.layer import PersonalizationLayer  # noqa: E402
from agent.store import STATE, Store  # noqa: E402
from agent.tools import Tools  # noqa: E402
from agent.careem import CareemTools  # noqa: E402

app = FastAPI(title="Voice agent: LLM brain + personalization")
S = {}


def build():
    store = Store()
    llm = LLM()
    memory = S.get("memory") or UserMemory(STATE, llm.models)  # Qdrant keeps a file lock, so reuse it
    layer = PersonalizationLayer(store)
    # mcp (default): Careem's tools through careem-mcp (sandbox or production); mock: the offline JSON catalog
    if os.getenv("CAREEM_MODE", "mcp").lower() == "mcp":
        tools = CareemTools(store, memory, layer.services["places"])
    else:
        tools = Tools(store, memory)
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
            "careem_mode": os.getenv("CAREEM_MODE", "mcp").lower(),
            "events": st.events(user_id)[-12:][::-1], "llm_calls": S["brain"].llm.calls}


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

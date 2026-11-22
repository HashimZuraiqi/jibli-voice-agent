"""Long-term user memory on Amazon Bedrock AgentCore Memory (default). Same interface as the Mem0 backup in memory.py.

How it maps:
- each user is an AgentCore actor (actorId = user_id)
- what the user says -> create_event (short-term); AgentCore's semantic + user-preference strategies extract
  long-term facts into /users/{actorId}/facts/ and /users/{actorId}/preferences/ (async, usually under a minute)
- seed facts the family gave at sign-up -> batch_create_memory_records (instant, no extraction)
- recall -> retrieve_memory_records (semantic search), list -> list_memory_records, forget -> delete_memory_record

Create the memory resource once with scripts/create_agentcore_memory.py and put its id in .env (AGENTCORE_MEMORY_ID).
Credentials come from the environment like the LLM; the event's expire hourly, so an expired token reloads .env once.
"""
import datetime as dt
import json
import os
import uuid
from pathlib import Path

from .personalization.guardrails import safe_to_remember

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"
NAMESPACES = ("/users/{uid}/facts/", "/users/{uid}/preferences/")
EXPIRED = {"ExpiredTokenException", "ExpiredToken", "UnrecognizedClientException", "InvalidSignatureException"}


def fact_text(record):
    """The user-preference strategy stores JSON ({"context", "preference", "categories"}); show just the preference."""
    text = record["content"]["text"]
    if text.startswith("{"):
        try:
            return json.loads(text).get("preference") or text
        except (ValueError, AttributeError):
            pass
    return text


class AgentCoreMemory:
    def __init__(self, seed_facts, memory_id=None, region=None, client=None):
        self.memory_id = memory_id or os.getenv("AGENTCORE_MEMORY_ID", "")
        if not self.memory_id:
            raise RuntimeError("AGENTCORE_MEMORY_ID is not set: run scripts/create_agentcore_memory.py once and "
                               "paste the id into ai-core/.env (or set MEMORY_PROVIDER=mem0)")
        self.region = region or os.getenv("AWS_REGION", "us-east-1")
        self.seed_facts = seed_facts
        # true = also store the raw sentence as a record right away, so "what do you know about me?" shows it
        # instantly in the demo instead of after AgentCore's extraction finishes
        self.instant = os.getenv("AGENTCORE_INSTANT_FACTS", "true").lower() == "true"
        self._client = client
        self._seeded = set()
        # AgentCore's list/retrieve index lags writes by ~5-15 s, so remember our own recent writes and deletes
        # and merge them in until the service catches up (else a fact learned this turn is missing next turn,
        # and a fact deleted with × comes back on refresh)
        self._pending = {}  # user_id -> {record_id: text} written but maybe not listed yet
        self._deleted = {}  # user_id -> record ids deleted but maybe still listed

    # -- AWS plumbing --
    def client(self, fresh=False):
        if self._client is None or fresh:
            import boto3
            if fresh and ENV_FILE.exists():
                from dotenv import load_dotenv
                load_dotenv(ENV_FILE, override=True)
            self._client = boto3.session.Session().client("bedrock-agentcore", region_name=self.region)
        return self._client

    def call(self, op, **kw):
        try:
            return getattr(self.client(), op)(memoryId=self.memory_id, **kw)
        except Exception as e:
            code = getattr(e, "response", {}).get("Error", {}).get("Code", "")
            if code not in EXPIRED:
                raise
            return getattr(self.client(fresh=True), op)(memoryId=self.memory_id, **kw)

    @staticmethod
    def ns(user_id):
        return [n.format(uid=user_id) for n in NAMESPACES]

    def _write(self, user_id, facts):
        now = dt.datetime.now(dt.timezone.utc)
        recs = [{"requestIdentifier": uuid.uuid4().hex[:32], "namespaces": [self.ns(user_id)[0]],
                 "content": {"text": f}, "timestamp": now} for f in facts]
        if not recs:
            return
        r = self.call("batch_create_memory_records", records=recs)
        text = {rec["requestIdentifier"]: rec["content"]["text"] for rec in recs}
        for ok in r.get("successfulRecords", []):
            if ok.get("memoryRecordId") and ok.get("requestIdentifier") in text:
                self._pending.setdefault(user_id, {})[ok["memoryRecordId"]] = text[ok["requestIdentifier"]]
        if r.get("failedRecords"):
            f = r["failedRecords"][0]
            raise RuntimeError(f"memory record not stored: {f.get('errorCode')} {f.get('errorMessage', '')[:100]}")

    # -- same interface as the Mem0 UserMemory --
    def seed(self, user_id):
        if user_id in self._seeded:
            return
        if not self.all(user_id):
            self._write(user_id, self.seed_facts.get(user_id, []))
        self._seeded.add(user_id)

    def learn(self, user_id, text):
        """Send what the user said to AgentCore (it extracts the facts). Returns (stored, reason)."""
        ok, reason = safe_to_remember(text)
        if not ok:
            return False, reason
        try:
            now = dt.datetime.now(dt.timezone.utc)
            self.call("create_event", actorId=user_id, sessionId=f"{user_id}-{now:%Y%m%d}", eventTimestamp=now,
                      payload=[{"conversational": {"content": {"text": text}, "role": "USER"}}])
            if self.instant:
                self._write(user_id, [text])
            return True, "ok"
        except Exception as e:  # a failed memory write must not break the conversation
            return False, f"memory write failed: {type(e).__name__}: {str(e)[:120]}"

    def recall(self, user_id, query, k=5):
        hits = []
        for ns in self.ns(user_id):
            try:
                r = self.call("retrieve_memory_records", namespace=ns,
                              searchCriteria={"searchQuery": query[:1000] or "preferences", "topK": k})
            except Exception:
                continue  # recall is best effort: the agent still works without memory
            hits += r.get("memoryRecordSummaries", [])
        hits.sort(key=lambda h: h.get("score") or 0, reverse=True)
        found = [{"id": h["memoryRecordId"], "fact": fact_text(h)} for h in hits
                 if h["memoryRecordId"] not in self._deleted.get(user_id, ())]
        # facts written seconds ago may not be searchable yet: put them first, newest first (this conversation)
        if self._pending.get(user_id):
            try:
                self.all(user_id)  # drops the ones the service has indexed meanwhile
            except Exception:
                pass
        ids = {f["id"] for f in found}
        fresh = [{"id": i, "fact": t} for i, t in reversed(self._pending.get(user_id, {}).items()) if i not in ids]
        return (fresh + found)[:k]

    def all(self, user_id):
        out = self._list(user_id)
        listed = {m["id"] for m in out}
        pending = self._pending.get(user_id, {})
        for i in [i for i in pending if i in listed]:
            del pending[i]  # the service lists it now
        deleted = self._deleted.setdefault(user_id, set())
        deleted &= listed  # forget deletes the service no longer lists
        return [m for m in out if m["id"] not in deleted] + [{"id": i, "fact": t} for i, t in pending.items()]

    def _list(self, user_id):
        out = []
        for ns in self.ns(user_id):
            token = None
            while True:
                kw = {"namespace": ns, "maxResults": 100, **({"nextToken": token} if token else {})}
                r = self.call("list_memory_records", **kw)
                out += [{"id": m["memoryRecordId"], "fact": fact_text(m)} for m in r.get("memoryRecordSummaries", [])]
                token = r.get("nextToken")
                if not token:
                    break
        return out

    def forget(self, user_id, memory_id=None):
        """Delete one fact by id, or everything about the user."""
        ids = [m["id"] for m in self.all(user_id)]
        if memory_id:
            if memory_id not in ids:
                return 0
            ids = [memory_id]
        for i in ids:
            self.call("delete_memory_record", memoryRecordId=i)
            self._deleted.setdefault(user_id, set()).add(i)
            self._pending.get(user_id, {}).pop(i, None)
        if not memory_id:
            self._seeded.discard(user_id)  # a reset user gets the sign-up facts again
        return len(ids)

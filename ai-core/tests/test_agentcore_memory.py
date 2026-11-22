"""AgentCore Memory backend against a fake bedrock-agentcore client (no AWS needed)."""
from agent.agentcore_memory import AgentCoreMemory


class FakeClientError(Exception):
    def __init__(self, code):
        self.response = {"Error": {"Code": code}}


class FakeAgentCore:
    def __init__(self):
        self.records, self.events, self.n, self.expire_next = {}, [], 0, False
        self.lag = False  # like the real service: new records are not listed yet, deleted ones still are
        self.unindexed, self.stale = set(), {}

    def _check(self, memoryId):
        assert memoryId == "JibliMemory-abc1234567"
        if self.expire_next:
            self.expire_next = False
            raise FakeClientError("ExpiredTokenException")

    def batch_create_memory_records(self, memoryId, records):
        self._check(memoryId)
        ok = []
        for r in records:
            self.n += 1
            rid = f"mem-{self.n}"
            self.records[rid] = {"ns": r["namespaces"][0], "text": r["content"]["text"]}
            if self.lag:
                self.unindexed.add(rid)
            ok.append({"memoryRecordId": rid, "status": "SUCCEEDED", "requestIdentifier": r["requestIdentifier"]})
        return {"successfulRecords": ok, "failedRecords": []}

    def catch_up(self):
        self.unindexed, self.stale = set(), {}

    def create_event(self, memoryId, actorId, sessionId, eventTimestamp, payload):
        self._check(memoryId)
        self.events.append((actorId, payload[0]["conversational"]["content"]["text"]))
        return {"event": {"eventId": "e1"}}

    def _summaries(self, ns):
        visible = {**{i: r for i, r in self.records.items() if i not in self.unindexed}, **self.stale}
        return [{"memoryRecordId": i, "content": {"text": r["text"]}, "score": 0.5}
                for i, r in visible.items() if r["ns"] == ns]

    def list_memory_records(self, memoryId, namespace, maxResults=20, nextToken=None):
        self._check(memoryId)
        return {"memoryRecordSummaries": self._summaries(namespace)}

    def retrieve_memory_records(self, memoryId, namespace, searchCriteria):
        self._check(memoryId)
        words = searchCriteria["searchQuery"].lower().split()
        hits = [h for h in self._summaries(namespace) if any(w in h["content"]["text"].lower() for w in words)]
        return {"memoryRecordSummaries": hits[:searchCriteria["topK"]]}

    def delete_memory_record(self, memoryId, memoryRecordId):
        self._check(memoryId)
        r = self.records.pop(memoryRecordId)
        if self.lag:
            self.stale[memoryRecordId] = r
        return {"memoryRecordId": memoryRecordId}


def make(monkeypatch=None, instant="true"):
    import os
    os.environ["AGENTCORE_INSTANT_FACTS"] = instant
    fake = FakeAgentCore()
    mem = AgentCoreMemory({"um_khaled": ["Prefers the small Arabic bread", "Her son Khaled pays"]},
                          memory_id="JibliMemory-abc1234567", client=fake)
    mem.client = lambda fresh=False: fake  # no boto3 / .env reload in tests
    return mem, fake


def test_seed_once_and_list():
    mem, fake = make()
    mem.seed("um_khaled")
    mem.seed("um_khaled")
    assert sorted(m["fact"] for m in mem.all("um_khaled")) == ["Her son Khaled pays", "Prefers the small Arabic bread"]
    assert mem.all("abu_sami") == []  # users are separate namespaces


def test_learn_sends_event_and_instant_record():
    mem, fake = make()
    assert mem.learn("um_khaled", "جوزي ما بوكل سكر") == (True, "ok")
    assert fake.events == [("um_khaled", "جوزي ما بوكل سكر")]
    assert [m["fact"] for m in mem.all("um_khaled")] == ["جوزي ما بوكل سكر"]


def test_learn_without_instant_only_sends_event():
    mem, fake = make(instant="false")
    mem.learn("um_khaled", "I like cardamom coffee")
    assert fake.events and mem.all("um_khaled") == []


def test_sensitive_never_reaches_aws():
    mem, fake = make()
    ok, why = mem.learn("um_khaled", "رقمي الوطني 9851234567")
    assert not ok and why.startswith("sensitive")
    assert fake.events == [] and fake.records == {}


def test_recall_and_forget():
    mem, fake = make()
    mem.seed("um_khaled")
    hits = mem.recall("um_khaled", "bread")
    assert [h["fact"] for h in hits] == ["Prefers the small Arabic bread"]
    assert mem.forget("um_khaled", hits[0]["id"]) == 1
    assert mem.forget("um_khaled", "not-an-id") == 0
    assert mem.forget("um_khaled") == 1 and mem.all("um_khaled") == []
    mem.seed("um_khaled")  # after a full reset the sign-up facts come back
    assert len(mem.all("um_khaled")) == 2


def test_expired_credentials_retry_once():
    mem, fake = make()
    fake.expire_next = True
    mem.seed("um_khaled")
    assert len(mem.all("um_khaled")) == 2


def test_index_lag_hides_nothing_and_resurrects_nothing():
    """Live AgentCore lists new records ~5-15 s late and deleted ones a little longer; the backend covers the gap."""
    mem, fake = make()
    fake.lag = True
    mem.seed("um_khaled")
    assert len(mem.all("um_khaled")) == 2  # seeds show at once, not after the index catches up
    mem.learn("um_khaled", "جوزي ما بوكل سكر")
    assert mem.recall("um_khaled", "sugar")[0]["fact"] == "جوزي ما بوكل سكر"  # this turn's fact reaches next turn
    sugar = [m for m in mem.all("um_khaled") if m["fact"] == "جوزي ما بوكل سكر"][0]
    fake.catch_up()
    assert mem.forget("um_khaled", sugar["id"]) == 1
    assert all(m["id"] != sugar["id"] for m in mem.all("um_khaled"))  # × removes it from the panel right away
    assert all(h["id"] != sugar["id"] for h in mem.recall("um_khaled", "sugar"))
    assert mem.forget("um_khaled") == 2 and mem.all("um_khaled") == []  # full reset, though still listed
    mem.seed("um_khaled")
    assert len(mem.all("um_khaled")) == 2  # sign-up facts come back after a reset
    fake.catch_up()
    assert len(mem.all("um_khaled")) == 2 and not mem._pending["um_khaled"] and not mem._deleted["um_khaled"]


def test_preference_records_show_the_preference_not_json():
    mem, fake = make()
    fake.records["mem-p"] = {"ns": "/users/um_khaled/preferences/", "text": '{"context":"cooking at home",'
                             '"preference":"Husband does not eat sugar","categories":["food"]}'}
    fake.records["mem-f"] = {"ns": "/users/um_khaled/facts/", "text": "{not json"}
    assert sorted(m["fact"] for m in mem.all("um_khaled")) == ["Husband does not eat sugar", "{not json"]
    assert mem.recall("um_khaled", "cooking")[0]["fact"] == "Husband does not eat sugar"


def test_only_statements_become_instant_facts():
    from agent.agentcore_memory import looks_like_fact
    for fact in ("جوزي ما بوكل سكر", "ابني خالد هو اللي بدفع", "بفضل الخبز الصغير مش الكبير", "My husband takes no sugar"):
        assert looks_like_fact(fact), fact
    for filler in ("اه يا ريت", "شو بتعرف عني؟", "ابعتلي خبز وحليب وبيض", "لا مش هلق", "تمام", "انسى موضوع السكر",
                   "what do you know about me"):
        assert not looks_like_fact(filler), filler


def test_filler_goes_to_agentcore_but_not_the_panel():
    mem, fake = make()
    assert mem.learn("um_khaled", "اه يا ريت") == (True, "ok")
    assert fake.events == [("um_khaled", "اه يا ريت")]  # AgentCore still sees it and extracts what it wants
    assert mem.all("um_khaled") == []

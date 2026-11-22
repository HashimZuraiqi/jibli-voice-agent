"""Long-term user memory with Mem0 (OpenRouter LLM for fact extraction, local multilingual embeddings, local Qdrant)."""
import logging
import os

os.environ.setdefault("MEM0_TELEMETRY", "False")  # no usage data sent to Mem0's analytics

from mem0 import Memory  # noqa: E402

from .personalization.guardrails import safe_to_remember

logging.getLogger("mem0").setLevel(logging.ERROR)

# facts the family gave at sign-up, stored without an LLM call
SEED_FACTS = {
    "um_khaled": ["Her husband Abu Khaled takes no sugar: buy the sweetener, never regular sugar",
                  "Prefers the small Arabic bread, not the big one",
                  "Her son Khaled pays and confirms the orders"],
    "abu_sami": ["His daughter Rana pays and confirms the orders",
                 "Likes his Arabic coffee with cardamom"],
    "new_user": ["Her grandson Omar pays and confirms the orders"],
}


class UserMemory:
    def __init__(self, state_dir, models):
        self.infer = os.getenv("MEM0_INFER", "true").lower() == "true"
        self.mem = Memory.from_config({
            "llm": {"provider": "openai", "config": {"model": models[0], "models": models, "temperature": 0}},
            "embedder": {"provider": "fastembed",
                         "config": {"model": "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"}},
            "vector_store": {"provider": "qdrant", "config": {"path": str(state_dir / "qdrant"), "collection_name": "users",
                                                              "embedding_model_dims": 384, "on_disk": True}},
            "history_db_path": str(state_dir / "mem0_history.db"),
        })

    def seed(self, user_id):
        if not self.all(user_id):
            for fact in SEED_FACTS.get(user_id, []):
                self.mem.add(fact, user_id=user_id, infer=False)

    def learn(self, user_id, text):
        """Store what the user said (Mem0 extracts the facts). Returns (stored, reason)."""
        ok, reason = safe_to_remember(text)
        if not ok:
            return False, reason
        try:
            self.mem.add([{"role": "user", "content": text}], user_id=user_id, infer=self.infer)
            return True, "ok"
        except Exception as e:  # a failed memory write must not break the conversation
            return False, f"memory write failed: {type(e).__name__}: {str(e)[:120]}"

    def recall(self, user_id, query, k=5):
        res = self.mem.search(query, filters={"user_id": user_id}, top_k=k, threshold=0.2)["results"]
        return [{"id": r["id"], "fact": r["memory"]} for r in res]

    def all(self, user_id):
        return [{"id": r["id"], "fact": r["memory"]} for r in self.mem.get_all(filters={"user_id": user_id}, top_k=100)["results"]]

    def forget(self, user_id, memory_id=None):
        """Delete one fact by id, or everything about the user."""
        if memory_id:
            if memory_id not in {m["id"] for m in self.all(user_id)}:
                return 0
            self.mem.delete(memory_id)
            return 1
        n = len(self.all(user_id))
        self.mem.delete_all(user_id=user_id)
        return n

"""LLM client: OpenRouter free models through the OpenAI SDK, with retries and model fallback."""
import os
import time

from openai import APIError, APIStatusError, OpenAI

DEFAULT_MODELS = "google/gemma-4-31b-it:free,nvidia/nemotron-3-ultra-550b-a55b:free"


class QuotaExceeded(Exception):
    pass


class LLM:
    def __init__(self):
        self.models = [m.strip() for m in os.getenv("LLM_MODELS", DEFAULT_MODELS).split(",") if m.strip()]
        self.client = OpenAI(base_url=os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
                             api_key=os.getenv("OPENROUTER_API_KEY", ""), timeout=90, max_retries=0)
        self.calls = 0

    def chat(self, messages, tools=None):
        last = None
        for model in list(self.models):
            for attempt in range(3):
                try:
                    r = self.client.chat.completions.create(model=model, messages=messages, tools=tools or None,
                                                            temperature=0, seed=7)
                    self.calls += 1
                    if model != self.models[0]:  # stick with the model that answers
                        self.models.remove(model)
                        self.models.insert(0, model)
                    return r.choices[0].message, {"model": r.model, "usage": r.usage.model_dump() if r.usage else None}
                except APIStatusError as e:
                    last = e
                    if "free-models-per-day" in str(e):
                        raise QuotaExceeded("OpenRouter free daily limit (50 requests per account) is used up; "
                                            "it resets at 00:00 UTC. Use another key or add credit.") from e
                    if e.status_code in (400, 401, 403, 404) or (e.status_code == 429 and attempt >= 1):
                        break
                except APIError as e:
                    last = e
                time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"all models failed: {last}")

"""LLM client. Default: Claude on Amazon Bedrock (Converse API). Fallback: OpenRouter free models (LLM_PROVIDER=openrouter).

Both return the same shape to the brain: (message, meta), where message has .content and .tool_calls
(each with .id, .function.name, .function.arguments as a JSON string), like the OpenAI SDK.

AWS credentials are never in code: boto3 reads them from the environment / default chain. The event's CLI credentials
expire every hour; paste the new export lines into ai-core/.env and the next call picks them up (no restart).
"""
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MODELS = "google/gemma-4-31b-it:free,nvidia/nemotron-3-ultra-550b-a55b:free"
DEFAULT_BEDROCK_MODEL = "global.anthropic.claude-sonnet-5-5"
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class QuotaExceeded(Exception):
    pass


@dataclass
class Fn:
    name: str
    arguments: str


@dataclass
class ToolCall:
    id: str
    function: Fn
    type: str = "function"


@dataclass
class Message:
    content: str | None
    tool_calls: list = field(default_factory=list)


def to_converse(messages):
    """OpenAI-style chat messages -> (system blocks, Converse messages).

    Converse needs: system text apart, tool results as user turns, strict user/assistant alternation,
    no empty text blocks, and a user turn first.
    """
    system, out = [], []

    def push(role, blocks):
        blocks = [b for b in blocks if not ("text" in b and not b["text"].strip())]
        if not blocks:
            return
        if out and out[-1]["role"] == role:
            out[-1]["content"].extend(blocks)
        else:
            out.append({"role": role, "content": blocks})

    for m in messages:
        role, content = m["role"], m.get("content") or ""
        if role == "system":
            if content.strip():
                system.append({"text": content})
        elif role == "user":
            push("user", [{"text": content}])
        elif role == "assistant":
            blocks = [{"text": content}]
            for c in m.get("tool_calls") or []:
                fn = c["function"]
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                blocks.append({"toolUse": {"toolUseId": c["id"], "name": fn["name"],
                                           "input": args if isinstance(args, dict) else {"value": args}}})
            push("assistant", blocks)
        elif role == "tool":
            try:
                data = json.loads(content)
                body = [{"json": data}] if isinstance(data, dict) else [{"text": content}]
            except json.JSONDecodeError:
                body = [{"text": content or "(empty)"}]
            push("user", [{"toolResult": {"toolUseId": m["tool_call_id"], "content": body}}])
    if out and out[0]["role"] != "user":  # e.g. history starts with our proactive reminder
        out.insert(0, {"role": "user", "content": [{"text": "(Sanad sent the user a voice note first.)"}]})
    if not out:
        out = [{"role": "user", "content": [{"text": "Go."}]}]
    return system, out


def to_tool_config(tools):
    if not tools:
        return None
    return {"tools": [{"toolSpec": {"name": t["function"]["name"], "description": t["function"]["description"],
                                    "inputSchema": {"json": t["function"]["parameters"]}}} for t in tools]}


def from_converse(resp):
    texts, calls = [], []
    for b in resp["output"]["message"]["content"]:
        if "text" in b:
            texts.append(b["text"])
        elif "toolUse" in b:
            u = b["toolUse"]
            calls.append(ToolCall(u["toolUseId"], Fn(u["name"], json.dumps(u.get("input") or {}, ensure_ascii=False))))
    return Message("".join(texts) or None, calls)


class BedrockLLM:
    def __init__(self, client=None):
        model = os.getenv("BEDROCK_MODEL", DEFAULT_BEDROCK_MODEL)
        self.models = [m.strip() for m in model.split(",") if m.strip()]
        self.region = os.getenv("AWS_REGION", "us-east-1")
        self.max_tokens = int(os.getenv("BEDROCK_MAX_TOKENS", "1024"))
        self._client = client
        self.calls = 0

    def client(self, fresh=False):
        if self._client is None or fresh:
            import boto3
            if fresh and ENV_FILE.exists():  # pick up credentials pasted into .env after they expired
                from dotenv import load_dotenv
                load_dotenv(ENV_FILE, override=True)
            self._client = boto3.session.Session().client("bedrock-runtime", region_name=self.region)
        return self._client

    def chat(self, messages, tools=None):
        from botocore.exceptions import ClientError
        system, msgs = to_converse(messages)
        # no temperature: Claude 5.5 models on Bedrock reject it (ValidationException)
        kw = {"messages": msgs, "system": system, "inferenceConfig": {"maxTokens": self.max_tokens}}
        if tools:
            kw["toolConfig"] = to_tool_config(tools)
        last = None
        for model in list(self.models):
            for attempt in range(4):
                try:
                    r = self.client(fresh=attempt > 0 and isinstance(last, ClientError) and _expired(last)).converse(
                        modelId=model, **kw)
                    self.calls += 1
                    return from_converse(r), {"model": model, "usage": r.get("usage")}
                except ClientError as e:
                    last = e
                    code = e.response.get("Error", {}).get("Code", "")
                    if _expired(e):
                        if attempt >= 1:
                            raise RuntimeError("AWS credentials expired: open link.careem.com/htjordan, click A, and "
                                               "paste the new export lines into ai-core/.env") from e
                        continue
                    if code in ("ThrottlingException", "ServiceUnavailableException", "ModelNotReadyException"):
                        time.sleep(2 * (attempt + 1))
                        continue
                    break  # validation / access errors: try the next model
        raise RuntimeError(f"Bedrock failed: {last}")


def _expired(e):
    code = e.response.get("Error", {}).get("Code", "")
    return code in ("ExpiredTokenException", "ExpiredToken", "UnrecognizedClientException", "InvalidSignatureException")


class OpenRouterLLM:
    def __init__(self):
        from openai import OpenAI
        self.models = [m.strip() for m in os.getenv("LLM_MODELS", DEFAULT_MODELS).split(",") if m.strip()]
        self.client = OpenAI(base_url=os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1"),
                             api_key=os.getenv("OPENROUTER_API_KEY", ""), timeout=90, max_retries=0)
        self.calls = 0

    def chat(self, messages, tools=None):
        from openai import APIError, APIStatusError
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


def LLM():
    """LLM_PROVIDER=bedrock (default) or openrouter."""
    provider = os.getenv("LLM_PROVIDER", "bedrock").lower()
    llm = OpenRouterLLM() if provider == "openrouter" else BedrockLLM()
    llm.provider = provider
    return llm

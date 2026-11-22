"""Bedrock adapter tests with a fake client (no AWS needed)."""
import json

from botocore.exceptions import ClientError

from agent.llm import BedrockLLM, to_converse


def test_to_converse_shapes_history():
    msgs = [{"role": "system", "content": "be kind"},
            {"role": "assistant", "content": "reminder"},
            {"role": "user", "content": "اه"},
            {"role": "assistant", "content": "", "tool_calls": [
                {"id": "t1", "type": "function", "function": {"name": "view_cart", "arguments": "{}"}},
                {"id": "t2", "type": "function", "function": {"name": "search_catalog", "arguments": '{"query":"خبز"}'}}]},
            {"role": "tool", "tool_call_id": "t1", "content": json.dumps({"lines": [], "total_jod": 0})},
            {"role": "tool", "tool_call_id": "t2", "content": json.dumps({"results": "no matching products"})}]
    system, out = to_converse(msgs)
    assert system == [{"text": "be kind"}]
    assert [m["role"] for m in out] == ["user", "assistant", "user", "assistant", "user"]
    assert [b["toolUse"]["name"] for b in out[3]["content"]] == ["view_cart", "search_catalog"]  # empty text dropped
    assert [b["toolResult"]["toolUseId"] for b in out[4]["content"]] == ["t1", "t2"]  # tool results merged


class Fake:
    def __init__(self, replies):
        self.replies, self.seen = list(replies), []

    def converse(self, **kw):
        self.seen.append(kw)
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def test_chat_returns_openai_like_tool_calls():
    fake = Fake([{"output": {"message": {"role": "assistant", "content": [
        {"text": "checking"}, {"toolUse": {"toolUseId": "x", "name": "view_cart", "input": {}}}]}},
        "usage": {"inputTokens": 1, "outputTokens": 1}}])
    llm = BedrockLLM(client=fake)
    tools = [{"type": "function", "function": {"name": "view_cart", "description": "d",
                                               "parameters": {"type": "object", "properties": {}, "required": []}}}]
    msg, meta = llm.chat([{"role": "user", "content": "hi"}], tools)
    assert msg.content == "checking" and msg.tool_calls[0].function.name == "view_cart"
    assert json.loads(msg.tool_calls[0].function.arguments) == {}
    assert fake.seen[0]["toolConfig"]["tools"][0]["toolSpec"]["name"] == "view_cart"
    assert "temperature" not in fake.seen[0]["inferenceConfig"]  # current Claude models on Bedrock reject it


def test_throttling_is_retried(monkeypatch):
    monkeypatch.setattr("agent.llm.time.sleep", lambda s: None)
    err = ClientError({"Error": {"Code": "ThrottlingException", "Message": "slow"}}, "Converse")
    ok = {"output": {"message": {"content": [{"text": "هلا"}]}}}
    llm = BedrockLLM(client=Fake([err, ok]))
    msg, _ = llm.chat([{"role": "user", "content": "hi"}])
    assert msg.content == "هلا" and msg.tool_calls == []

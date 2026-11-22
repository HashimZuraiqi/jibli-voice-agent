"""spec/BUILD.md §7 acceptance tests, run against a real server over streamable HTTP.
Run: ../.venv/bin/python -m pytest -q test_acceptance.py"""
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import anyio
import pytest
from jsonschema import Draft202012Validator

import server

HERE = Path(__file__).resolve().parent
LOC = {"latitude": 25.0866, "longitude": 55.1474}


@pytest.fixture(scope="module")
def srv(tmp_path_factory):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    overrides = tmp_path_factory.mktemp("run") / "overrides.json"
    overrides.write_text("{}")
    env = dict(os.environ, CAREEM_MCP_OVERRIDES=str(overrides))
    p = subprocess.Popen([sys.executable, str(HERE / "server.py"), "--port", str(port)], env=env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(url + "/health", timeout=1)
            break
        except OSError:
            time.sleep(0.1)
    yield url + "/mcp", overrides
    p.terminate()


def run(url, fn):
    from mcp import Client

    async def go():
        async with Client(url) as c:
            return await fn(c)
    return anyio.run(go)


def call(url, name, args):
    return run(url, lambda c: c.call_tool(name, args))


def test_1_initialize(srv):
    info = run(srv[0], lambda c: _ret(c.server_info))
    assert (info.name, info.version, info.title) == ("careem-mcp-service", "v1.0.0", None)
    assert not run(srv[0], lambda c: _ret(c.instructions))


async def _ret(v):
    return v


def test_2_tools_and_resources(srv):
    files = server.load_all()
    tools = run(srv[0], lambda c: c.list_tools()).tools
    assert len(tools) == len(files) == 42
    for t in tools:
        got = t.model_dump(by_alias=True, exclude_none=True, mode="json")
        assert got == files[t.name]["definition"], t.name
    res = run(srv[0], lambda c: c.list_resources()).resources
    assert [str(r.uri) for r in res] == ["ui://careem-mcp-app"]


def test_3_4_5_menu(srv):
    r = call(srv[0], "food_get_restaurant_menu", {"restaurant_id": 30104, **LOC})
    assert not r.is_error and r.structured_content["restaurant"]["id"] == 30104
    assert r.structured_content["restaurant"]["name"]["value"] == "Morning Syrniki Café"
    r = call(srv[0], "food_get_restaurant_menu", {"restaurant_id": 30101, **LOC})
    assert r.structured_content["restaurant"]["name"]["value"] == "Shawarma Station"
    r = call(srv[0], "food_get_restaurant_menu", {"restaurant_id": 1, **LOC})
    assert not r.is_error and r.structured_content["error"] == "failed to get restaurant menu: unexpected response status 404"


def test_6_validation(srv):
    r = call(srv[0], "food_get_restaurant_menu", {"restaurant_id": "x", **LOC})
    assert r.is_error and r.content[0].text.startswith('validating "arguments"')
    assert call(srv[0], "food_get_restaurant_menu", {}).is_error


def test_7_search(srv):
    assert call(srv[0], "food_merchant_search", {"query": "sushi", **LOC}).structured_content["restaurants"][0]["id"] == 30102
    assert call(srv[0], "food_merchant_search", {"query": "NOPE", **LOC}).structured_content["restaurants"] == []
    assert call(srv[0], "food_merchant_search", {"query": "sushi", "longitude": 55.1474}).is_error


def test_8_reverse_geocode(srv):
    assert call(srv[0], "reverse_geocode", LOC).structured_content["location"]["locationUuid"] == "LOC-50001"
    assert "error" in call(srv[0], "reverse_geocode", {"latitude": 91, "longitude": 55}).structured_content


def test_9_forced_scenario(srv):
    url, overrides = srv
    overrides.write_text(json.dumps({"food_get_restaurant_menu": "upstream-unavailable"}))
    assert "error" in call(url, "food_get_restaurant_menu", {"restaurant_id": 30104, **LOC}).structured_content
    overrides.write_text("{}")
    assert call(url, "food_get_restaurant_menu", {"restaurant_id": 30104, **LOC}).structured_content["restaurant"]["id"] == 30104


def test_10_unknown_tool(srv):
    from mcp.shared.exceptions import MCPError
    with pytest.raises(BaseException) as e:
        call(srv[0], "does_not_exist", {})
    err = e.value
    while isinstance(err, BaseExceptionGroup):  # the client's task group wraps the error
        err = err.exceptions[0]
    assert isinstance(err, MCPError) and err.error.code == -32602


def _sample(schema):
    t = schema.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), "null")
    if "enum" in schema:
        return schema["enum"][0]
    if t == "object" or "properties" in schema:
        return {k: _sample(v) for k, v in (schema.get("properties") or {}).items()}
    if t == "array":
        return [_sample(schema.get("items") or {})]
    return {"string": "sample", "integer": 1, "number": 1, "boolean": False, "null": None}.get(t, "sample")


def _overlay(sample, match):
    if isinstance(match, dict):
        base = dict(sample) if isinstance(sample, dict) else {}
        for k, v in match.items():
            base[k] = _overlay(base.get(k), v)
        return base
    if isinstance(match, list):
        item = sample[0] if isinstance(sample, list) and sample else None
        return [_overlay(item, m) if isinstance(m, dict) else _overlay(None, m) for m in match]
    if isinstance(match, str):
        if match == "*":
            return sample if sample is not None else "sample"
        return match[1:] if match[:1] in "~=" else match
    return match


def test_11_every_scenario_matches_output_schema():
    for name, f in server.load_all().items():
        d = f["definition"]
        for s in f["scenarios"]:
            if s["is_error"]:
                continue
            args = _overlay(_sample(d["inputSchema"]), s["match"] or {})
            value = server.render(s["template"], args)
            if "outputSchema" in d:
                errs = list(Draft202012Validator(d["outputSchema"]).iter_errors(value))
                assert not errs, f"{name}/{s['name']}: {errs[0].message}"


def test_12_no_local_copy_hints():
    words = ("mock", "sandbox", "sbx", "fake", "dummy", "example.com")
    files = server.load_all()
    observable = [json.dumps(f["definition"]) for f in files.values()]
    observable += [s["template"] for f in files.values() for s in f["scenarios"]]
    observable += [server.WIDGET_HTML, json.dumps(server.WIDGET_META), server.SERVER_NAME]
    for text in observable:
        low = text.lower()
        assert not any(w in low for w in words), [w for w in words if w in low]

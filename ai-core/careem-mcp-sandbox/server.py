"""Local careem-mcp server built from Careem's spec (spec/BUILD.md): same tools and response shapes as production,
answered from the scenario files in spec/tools. No network calls, no credentials.

Run: python server.py [--port 8787] [--stdio]      (normally through careem_mcp.py start)
"""
import argparse
import datetime as dt
import json
import os
import random
import re
import sys
import uuid
from pathlib import Path
from zoneinfo import ZoneInfo

from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent
SPEC = Path(os.getenv("CAREEM_MCP_SPEC", HERE / "spec"))
OVERRIDES = Path(os.getenv("CAREEM_MCP_OVERRIDES", HERE / ".run" / "overrides.json"))
SERVER_NAME, SERVER_VERSION = "careem-mcp-service", "v1.0.0"
WIDGET_DOMAIN = os.getenv("CAREEM_MCP_WIDGET_DOMAIN", "https://careem-mcp-app.pages.dev")
ZONE = ZoneInfo("Asia/Dubai")
BLOCK = re.compile(r"^```json[ \t]+(match|response|error|tool)[ \t]*\n(.*?)^```[ \t]*$", re.M | re.S)


class SpecError(Exception):
    pass


# ---------- parsing (spec/BUILD.md §2) ----------

def parse_file(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        raise SpecError(f"{path.name}: missing frontmatter")
    end = text.index("\n---\n", 4)
    front = {}
    for line in text[4:end].splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            front[k.strip()] = re.sub(r"\s+#.*$", "", v).strip().strip("'\"")
    if not front.get("tool"):
        raise SpecError(f"{path.name}: frontmatter has no tool")
    sections, title, buf, fence = [], None, [], False
    for line in text[end + 5:].splitlines(keepends=True):
        if line.startswith("```"):
            fence = not fence
        if not fence and line.startswith("## "):
            if title is not None:
                sections.append((title, "".join(buf)))
            title, buf = line[3:].strip(), []
        elif title is not None:
            buf.append(line)
    if title is not None:
        sections.append((title, "".join(buf)))

    definition, scenarios = None, []
    for title, body in sections:
        blocks = [(m.group(1), m.group(2)) for m in BLOCK.finditer(body)]
        if title == "Definition":
            tools = [b for k, b in blocks if k == "tool"]
            if len(tools) != 1:
                raise SpecError(f"{path.name}: Definition needs one json tool block")
            definition = json.loads(tools[0])
        elif title.startswith("Scenario:"):
            name = title.split(":", 1)[1].strip()
            matches = [b for k, b in blocks if k == "match"]
            outs = [(k, b) for k, b in blocks if k in ("response", "error")]
            if len(outs) != 1 or len(matches) > 1:
                raise SpecError(f"{path.name} scenario {name}: needs exactly one response/error block")
            scenarios.append({"name": name, "match": json.loads(matches[0]) if matches else None,
                              "is_error": outs[0][0] == "error", "template": outs[0][1]})
    if definition is None:
        raise SpecError(f"{path.name}: no Definition")
    if definition.get("name") != front["tool"]:
        raise SpecError(f"{path.name}: definition name {definition.get('name')} != {front['tool']}")
    if not scenarios or not any(s["match"] is None for s in scenarios):
        raise SpecError(f"{path.name}: needs a default scenario")
    for s in scenarios:  # fail fast on templates that are not valid JSON
        try:
            render(s["template"], {})
        except Exception as e:
            raise SpecError(f"{path.name} scenario {s['name']}: {e}") from e
    return {"tool": front["tool"], "path": path, "definition": definition, "scenarios": scenarios}


def load_all() -> dict:
    files = {}
    for p in sorted(SPEC.glob("tools/**/*.md")):
        if p.name == "README.md":
            continue
        f = parse_file(p)
        if f["tool"] in files:
            raise SpecError(f"duplicate tool {f['tool']}")
        files[f["tool"]] = f
    return files


# ---------- selection (§3 Scenario selection) ----------

def _text(v):
    return v if isinstance(v, str) else json.dumps(v, separators=(",", ":"))


def matches(want, got, present=True) -> bool:
    if not present:
        return False
    if isinstance(want, dict):
        return isinstance(got, dict) and all(k in got and matches(v, got[k]) for k, v in want.items())
    if isinstance(want, list):
        return isinstance(got, list) and all(any(matches(w, g) for g in got) for w in want)
    if isinstance(want, str):
        if got is None:
            return False
        if want == "*":
            return True
        if want.startswith("~"):
            return want[1:].lower() in _text(got).lower()
        if want.startswith("="):
            return _text(got).lower() == want[1:].lower()
        return _text(got).lower() == want.lower()
    if isinstance(want, bool) or isinstance(got, bool):  # JSON-equal: true is not 1
        return isinstance(want, bool) and isinstance(got, bool) and want == got
    return want == got  # numbers compare as numbers (0 == 0.0), null only matches null


def select(file, args, forced=None):
    if forced:
        for s in file["scenarios"]:
            if s["name"].lower() == forced.lower():
                return s, True
    for s in file["scenarios"]:
        if s["match"] is not None and matches(s["match"], args):
            return s, False
    return next(s for s in file["scenarios"] if s["match"] is None), False


# ---------- placeholders (§3 Placeholders) ----------

DUR = re.compile(r"(\d+)(ms|s|m|h)")


def _duration(s):
    total = dt.timedelta()
    for n, unit in DUR.findall(s):
        total += {"ms": dt.timedelta(milliseconds=int(n)), "s": dt.timedelta(seconds=int(n)),
                  "m": dt.timedelta(minutes=int(n)), "h": dt.timedelta(hours=int(n))}[unit]
    if DUR.sub("", s):
        raise SpecError(f"bad duration {s!r}")
    return total


def _ordinal(n):
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def _time(expr, base):
    m = re.fullmatch(r"(now|unixms|unix)([+-][0-9a-z]+)?(?:@([0-9a-z]+))?(?:\|(date|weekday|hhmm|daylabel))?", expr)
    if not m:
        return None
    kind, off, step, fmt = m.groups()
    t = base
    if off:
        t = t + _duration(off[1:]) if off[0] == "+" else t - _duration(off[1:])
    if step:
        sec = _duration(step).total_seconds()
        t = dt.datetime.fromtimestamp((t.timestamp() // sec) * sec, dt.timezone.utc)
    if kind == "unix":
        return int(t.timestamp())
    if kind == "unixms":
        return int(t.timestamp() * 1000)
    if fmt:
        z = t.astimezone(ZONE)
        return {"date": z.strftime("%Y-%m-%d"), "weekday": z.strftime("%A"), "hhmm": z.strftime("%H:%M"),
                "daylabel": f"{z.strftime('%a')}, {_ordinal(z.day)} {z.strftime('%b')}"}[fmt]
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _value(expr, args, base):
    expr = expr.strip()
    if expr == "args" or expr.startswith("args."):
        v = args
        for part in expr.split(".")[1:]:
            if isinstance(v, dict):
                v = v.get(part)
            elif isinstance(v, list) and part.isdigit() and int(part) < len(v):
                v = v[int(part)]
            else:
                v = None
        return v
    if expr == "uuid":
        return str(uuid.uuid4())
    if m := re.fullmatch(r"rand:(\d+)-(\d+)", expr):
        return random.randint(int(m.group(1)), int(m.group(2)))
    t = _time(expr, base)
    if t is None:
        raise SpecError(f"unknown placeholder {{{{{expr}}}}}")
    return t


def render(template: str, args: dict):
    base = dt.datetime.now(dt.timezone.utc).replace(microsecond=0)
    out, i, in_str = [], 0, False
    while i < len(template):
        if template.startswith("{{", i):
            j = template.index("}}", i)
            v = _value(template[i + 2:j], args, base)
            if in_str:
                s = v if isinstance(v, str) else json.dumps(v, separators=(",", ":"))
                out.append(json.dumps(s)[1:-1])
            else:
                out.append(json.dumps(v))
            i = j + 2
            continue
        c = template[i]
        if c == "\\" and in_str:
            out.append(template[i:i + 2])
            i += 2
            continue
        if c == '"':
            in_str = not in_str
        out.append(c)
        i += 1
    return json.loads("".join(out))


# ---------- calls ----------

def overrides():
    try:
        data = json.loads(OVERRIDES.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def with_defaults(schema, args):
    args = dict(args or {})
    for k, p in (schema.get("properties") or {}).items():
        if k not in args and isinstance(p, dict) and "default" in p:
            args[k] = p["default"]
    return args


def log(msg):
    print(msg, file=sys.stderr, flush=True)


def call(files, name, arguments):
    """Returns (value, is_error, text) for a known tool, following spec/BUILD.md §3 tools/call."""
    definition = files[name]["definition"]
    args = with_defaults(definition["inputSchema"], arguments)
    errors = sorted(Draft202012Validator(definition["inputSchema"]).iter_errors(args), key=lambda e: e.path)
    if errors:
        e = errors[0]
        where = "/".join(str(p) for p in e.absolute_path)
        return None, True, f'validating "arguments": {where + ": " if where else ""}{e.message}'
    try:
        file = parse_file(files[name]["path"])  # re-read: edits apply without a restart
        scenario, forced = select(file, args, overrides().get(name))
        value = render(scenario["template"], args)
    except Exception as e:
        log(f"{name}: internal error: {e}")
        return None, True, "internal server error"
    log(f"{name} -> {scenario['name']}{' (forced)' if forced else ''} {json.dumps(args, separators=(',', ':'))}")
    return value, scenario["is_error"], json.dumps(value, separators=(",", ":"))


WIDGET_HTML = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="color-scheme" content="light dark">
<title>Careem MCP App</title>
<link rel="stylesheet" href="{WIDGET_DOMAIN}/assets/index.css">
</head>
<body>
<div id="root"></div>
<script type="module" src="{WIDGET_DOMAIN}/assets/index.js"></script>
</body>
</html>"""
WIDGET_META = {
    "ui": {"resourceUri": "ui://careem-mcp-app",
           "csp": {"connectDomains": [WIDGET_DOMAIN],
                   "resourceDomains": [WIDGET_DOMAIN, "https://careem.s3.eu-west-1.amazonaws.com",
                                       "https://d1a3f4spazzrp4.cloudfront.net", "https://careem-catalog-media.media.careem.com",
                                       "https://partner-mot-prod.media.careem.com"],
                   "frameDomains": [], "baseUriDomains": []}},
    "prefersBorder": False, "domain": WIDGET_DOMAIN,
    "annotations": {"ttlMs": 60000, "destructiveHint": False, "openWorldHint": False, "readOnlyHint": True},
}


def build_server(files):
    from mcp import types
    from mcp.server.lowlevel import Server
    from mcp.shared.exceptions import MCPError

    tools = [types.Tool.model_validate(f["definition"]) for f in files.values()]
    resource = types.Resource.model_validate({"uri": "ui://careem-mcp-app", "name": "ui://careem-mcp-app",
                                              "description": "Careem Widget", "mimeType": "text/html;profile=mcp-app",
                                              "_meta": WIDGET_META})

    async def list_tools(ctx, params):
        return types.ListToolsResult(tools=tools)

    async def call_tool(ctx, params):
        if params.name not in files:
            raise MCPError(code=-32602, message=f'unknown tool "{params.name}"')
        value, is_error, text = call(files, params.name, params.arguments or {})
        return types.CallToolResult(content=[types.TextContent(type="text", text=text)],
                                    structured_content=value if isinstance(value, dict) else None, is_error=is_error)

    async def list_resources(ctx, params):
        return types.ListResourcesResult(resources=[resource])

    async def read_resource(ctx, params):
        if str(params.uri) != "ui://careem-mcp-app":
            raise MCPError(code=-32602, message=f"unknown resource {params.uri}")
        content = types.TextResourceContents.model_validate({"uri": "ui://careem-mcp-app", "mimeType": "text/html;profile=mcp-app",
                                                            "text": WIDGET_HTML, "_meta": WIDGET_META})
        return types.ReadResourceResult(contents=[content])

    return Server(SERVER_NAME, version=SERVER_VERSION, on_list_tools=list_tools, on_call_tool=call_tool,
                  on_list_resources=list_resources, on_read_resource=read_resource)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.getenv("CAREEM_MCP_PORT", "8787")))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--stdio", action="store_true")
    a = ap.parse_args()
    files = load_all()
    server = build_server(files)
    log(f"{SERVER_NAME}: {len(files)} tools loaded from {SPEC}")
    if a.stdio:
        import anyio
        from mcp.server.stdio import stdio_server

        async def run():
            async with stdio_server() as (r, w):
                await server.run(r, w, server.create_initialization_options())
        anyio.run(run)
        return

    import uvicorn
    from starlette.responses import JSONResponse
    from starlette.routing import Route

    async def health(request):
        return JSONResponse({"status": "ok", "tools": len(files)})

    app = server.streamable_http_app(host=a.host, custom_starlette_routes=[Route("/health", health)])
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()

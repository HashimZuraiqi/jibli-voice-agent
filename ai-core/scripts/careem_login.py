"""Sign in to the REAL Careem MCP (production) and save the token to ai-core/.env.

    .venv/bin/python scripts/careem_login.py            # opens the browser, sign in with your Careem account
    .venv/bin/python scripts/careem_login.py --refresh  # new access token from the saved refresh token

OAuth 2.0 Authorization Code + PKCE (S256) against Careem Identity, hackathon public client (no secret).
WARNING: production uses your real Careem account. Checkout places REAL orders and spends REAL money.
"""
import base64
import hashlib
import json
import os
import secrets
import sys
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

CLIENT_ID = "1790a895-9cef-48b7-9a57-ec5670d50c41"  # hackathon production client (public, PKCE)
MCP_URL = "https://mcp.careemapis.com/mcp"
REDIRECT = "http://localhost:8080/callback"  # must match a registered callback exactly
SCOPES = "openid profile offline_access"
ENV = Path(__file__).resolve().parents[1] / ".env"


def get_json(url):
    with urllib.request.urlopen(url, timeout=20) as r:
        return json.load(r)


def post_form(url, data):
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"Token request failed ({e.code}): {e.read().decode()[:400]}")


def endpoints():
    prm = get_json("https://mcp.careemapis.com/.well-known/oauth-protected-resource")
    issuer = (prm.get("authorization_servers") or ["https://identity.careem.com"])[0].rstrip("/")
    oidc = get_json(issuer + "/.well-known/openid-configuration")
    return oidc["authorization_endpoint"], oidc["token_endpoint"]


def save_env(values):
    lines = ENV.read_text(encoding="utf-8").splitlines() if ENV.exists() else []
    for k, v in values.items():
        if v is None:
            continue
        for i, line in enumerate(lines):
            if line.startswith(k + "="):
                lines[i] = f"{k}={v}"
                break
        else:
            lines.append(f"{k}={v}")
    ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")


def login(auth_url, token_url):
    verifier = secrets.token_urlsafe(64)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    url = auth_url + "?" + urllib.parse.urlencode({
        "response_type": "code", "client_id": CLIENT_ID, "redirect_uri": REDIRECT, "scope": SCOPES,
        "code_challenge": challenge, "code_challenge_method": "S256", "state": state, "resource": MCP_URL})
    got = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            got.update({k: v[0] for k, v in q.items()})
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write("<h2>Signed in. You can close this tab and go back to the terminal.</h2>".encode())

        def log_message(self, *a):
            pass

    server = HTTPServer(("127.0.0.1", 8080), Handler)
    print("Opening the Careem sign-in page. If it doesn't open, paste this into your browser:\n" + url)
    webbrowser.open(url)
    while "code" not in got and "error" not in got:
        server.handle_request()
    if "error" in got:
        sys.exit(f"Sign-in failed: {got}")
    if got.get("state") != state:
        sys.exit("Sign-in failed: state mismatch")
    return post_form(token_url, {"grant_type": "authorization_code", "code": got["code"], "redirect_uri": REDIRECT,
                                 "client_id": CLIENT_ID, "code_verifier": verifier, "resource": MCP_URL})


def main():
    auth_url, token_url = endpoints()
    if "--refresh" in sys.argv:
        from dotenv import dotenv_values
        rt = dotenv_values(ENV).get("CAREEM_REFRESH_TOKEN") or os.getenv("CAREEM_REFRESH_TOKEN")
        if not rt:
            sys.exit("No CAREEM_REFRESH_TOKEN in .env: run without --refresh to sign in")
        tok = post_form(token_url, {"grant_type": "refresh_token", "refresh_token": rt, "client_id": CLIENT_ID,
                                    "resource": MCP_URL})
    else:
        tok = login(auth_url, token_url)
    save_env({"CAREEM_MCP_TOKEN": tok["access_token"], "CAREEM_REFRESH_TOKEN": tok.get("refresh_token"),
              "CAREEM_MCP_URL": MCP_URL})
    print(f"Saved the token to {ENV} (expires in about {int(tok.get('expires_in', 0)) // 60} min). "
          "Set CAREEM_PROVIDER=mcp and restart the app.\n"
          "REMINDER: this is your REAL Careem account: checkout places a real order and spends real money.")


if __name__ == "__main__":
    main()

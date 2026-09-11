#!/usr/bin/env python3
"""Connect the copilot to your real LinkedIn account.

Runs LinkedIn's official OAuth 2.0 authorization-code flow: your browser opens,
you sign in *to LinkedIn* and approve, and LinkedIn hands this script a token.
Your password is never seen, typed here, or stored.

    python scripts/linkedin_connect.py

What it writes to .env:
    LINKEDIN_ACCESS_TOKEN   the member token (valid ~60 days)
    LINKEDIN_TOKEN_ISSUED_AT when the token was issued, for expiry warnings
    LINKEDIN_AUTHOR_URN     your person URN, needed to attribute posts
    LINKEDIN_PUBLISH_MODE   set to "api" once a token exists

Prerequisite (one time, ~2 minutes):
  1. https://www.linkedin.com/developers/apps -> Create app
  2. Products tab -> request "Share on LinkedIn" and "Sign In with LinkedIn
     using OpenID Connect" (both are self-serve)
  3. Auth tab -> add this redirect URL exactly:
         http://localhost:8765/callback
  4. Copy the Client ID and Client Secret into .env as
     LINKEDIN_CLIENT_ID / LINKEDIN_CLIENT_SECRET, or paste them when asked.
"""

from __future__ import annotations

import http.server
import json
import secrets
import socket
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = REPO_ROOT / ".env"

REDIRECT_PORT = 8765
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"
CALLBACK_TIMEOUT = 300  # seconds to wait for the user to approve in the browser
AUTH_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"

# w_member_social lets the copilot post as you; openid/profile identify you so
# the post can be attributed. Nothing here grants access to your connections.
SCOPES = "openid profile w_member_social"

_result: dict[str, str] = {}


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_response(404)
            self.end_headers()
            return
        params = urllib.parse.parse_qs(parsed.query)
        _result.update({k: v[0] for k, v in params.items()})

        ok = "code" in _result
        body = (
            "<h2>Connected.</h2><p>You can close this tab and go back to the terminal.</p>"
            if ok
            else f"<h2>LinkedIn refused.</h2><pre>{_result.get('error_description', 'unknown error')}</pre>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(
            f"<html><body style='font-family:system-ui;background:#0a1017;color:#e8edf4;"
            f"display:grid;place-items:center;height:100vh'><div>{body}</div></body></html>".encode()
        )

    def log_message(self, *args):  # silence the default access log
        pass


def read_env() -> dict[str, str]:
    values: dict[str, str] = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    return values


def write_env(updates: dict[str, str]) -> None:
    """Update .env in place, preserving comments and ordering."""
    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    remaining = dict(updates)
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.strip().startswith("#") else None
        if key in remaining:
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(line)
    if remaining:
        out.append("")
        out.append("# --- written by scripts/linkedin_connect.py ---")
        out.extend(f"{k}={v}" for k, v in remaining.items())
    ENV_PATH.write_text("\n".join(out).rstrip() + "\n")


def ask(prompt: str, existing: str = "") -> str:
    if existing:
        return existing
    try:
        return input(prompt).strip()
    except EOFError:
        return ""


def post_form(url: str, data: dict[str, str]) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def get_json(url: str, token: str) -> dict:
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        return sock.connect_ex(("127.0.0.1", port)) != 0


def main() -> int:
    env = read_env()
    client_id = ask("LinkedIn Client ID: ", env.get("LINKEDIN_CLIENT_ID", ""))
    client_secret = ask("LinkedIn Client Secret: ", env.get("LINKEDIN_CLIENT_SECRET", ""))

    if not client_id or not client_secret:
        print(
            "\nNeed a LinkedIn app first. Create one at\n"
            "  https://www.linkedin.com/developers/apps\n"
            "request the 'Share on LinkedIn' and 'Sign In with LinkedIn' products,\n"
            f"add the redirect URL  {REDIRECT_URI}\n"
            "then put the Client ID/Secret in .env and run this again.",
            file=sys.stderr,
        )
        return 1

    if not port_free(REDIRECT_PORT):
        print(f"Port {REDIRECT_PORT} is busy; free it and retry.", file=sys.stderr)
        return 1

    state = secrets.token_urlsafe(24)
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": REDIRECT_URI,
        "state": state,
        "scope": SCOPES,
    }
    url = f"{AUTH_URL}?{urllib.parse.urlencode(params)}"

    server = http.server.HTTPServer(("127.0.0.1", REDIRECT_PORT), _CallbackHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    print("\nOpening LinkedIn so you can approve access.")
    print("If the browser doesn't open, paste this:\n")
    print(f"  {url}\n")
    webbrowser.open(url)

    print("Waiting for you to approve…")
    # serve_forever runs on the background thread; wait here for the callback.
    waited = 0.0
    while not _result and waited < CALLBACK_TIMEOUT:
        time.sleep(0.5)
        waited += 0.5
    server.shutdown()

    if "error" in _result:
        print(f"\nLinkedIn returned an error: {_result.get('error_description', _result['error'])}",
              file=sys.stderr)
        return 1
    if "code" not in _result:
        print("\nTimed out waiting for approval.", file=sys.stderr)
        return 1
    if _result.get("state") != state:
        # Guards against a callback that did not originate from this run.
        print("\nState mismatch — ignoring this callback.", file=sys.stderr)
        return 1

    print("Exchanging the code for a token…")
    try:
        token_response = post_form(
            TOKEN_URL,
            {
                "grant_type": "authorization_code",
                "code": _result["code"],
                "redirect_uri": REDIRECT_URI,
                "client_id": client_id,
                "client_secret": client_secret,
            },
        )
    except urllib.error.HTTPError as exc:
        print(f"\nToken exchange failed ({exc.code}): {exc.read().decode()[:300]}", file=sys.stderr)
        return 1

    access_token = token_response.get("access_token")
    if not access_token:
        print(f"\nNo access token in the response: {token_response}", file=sys.stderr)
        return 1

    print("Reading your profile…")
    try:
        me = get_json(USERINFO_URL, access_token)
    except urllib.error.HTTPError as exc:
        print(
            f"\nGot a token but couldn't read your profile ({exc.code}). "
            "Make sure the 'Sign In with LinkedIn using OpenID Connect' product is added.",
            file=sys.stderr,
        )
        return 1

    subject = me.get("sub", "")
    author_urn = f"urn:li:person:{subject}" if subject else ""
    name = me.get("name", "")

    write_env(
        {
            "LINKEDIN_CLIENT_ID": client_id,
            "LINKEDIN_CLIENT_SECRET": client_secret,
            "LINKEDIN_ACCESS_TOKEN": access_token,
            "LINKEDIN_TOKEN_ISSUED_AT": datetime.now(UTC).isoformat(),
            "LINKEDIN_AUTHOR_URN": author_urn,
            "LINKEDIN_PUBLISH_MODE": "api",
        }
    )

    # Record who this is, for profile guidance and self-exclusion from networking.
    sys.path.insert(0, str(REPO_ROOT / "backend"))
    from app.core.settings_store import set_setting  # noqa: E402
    from app.database.migrations import run_migrations  # noqa: E402
    from app.database.session import session_scope  # noqa: E402

    run_migrations()
    with session_scope() as db:
        if name:
            set_setting(db, "linkedin_display_name", name)
        existing_url = env.get("LINKEDIN_PROFILE_URL", "")
        if existing_url:
            set_setting(db, "linkedin_profile_url", existing_url)

    expires_days = int(token_response.get("expires_in", 0)) // 86400
    print(f"\n  Connected as {name or 'your account'}.")
    print(f"  Author URN : {author_urn}")
    print(f"  Token valid: ~{expires_days} days" if expires_days else "")
    print("  Publishing mode is now 'api' — approved posts go out directly.")
    print("\n  Restart the backend for it to pick this up.")
    print("  Run this script again when the token expires.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

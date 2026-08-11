"""PKCE OAuth flow for Spotify.

Spotify supports the Authorization Code with PKCE flow for public clients —
no client secret needed. The user authorizes in their browser; we catch the
redirect on a localhost port and exchange the code for tokens.
"""

import base64
import hashlib
import secrets
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

from .api import exchange_code

AUTH_PORT = 47556
REDIRECT_URI = f"http://127.0.0.1:{AUTH_PORT}/callback"
SCOPES = (
    "user-read-playback-state "
    "user-modify-playback-state "
    "user-read-currently-playing"
)

_AUTH_HTML = b"""<!doctype html><html><head><meta charset="utf-8">
<title>Spotify Dock</title></head>
<body style="font-family:sans-serif;text-align:center;padding-top:64px;background:#111;color:#eee">
<h2 style="color:#1DB954">&#127911; Spotify Dock</h2>
<p>Authorization complete &mdash; you can close this tab and return to the terminal.</p>
</body></html>"""


def make_verifier() -> str:
    return secrets.token_urlsafe(64)


def make_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def auth_url(client_id: str, verifier: str) -> str:
    q = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "code_challenge_method": "S256",
            "code_challenge": make_challenge(verifier),
            "scope": SCOPES,
        }
    )
    return f"https://accounts.spotify.com/authorize?{q}"


def run_callback_server(timeout: float = 300.0) -> str:
    """Serve one redirect on 127.0.0.1:AUTH_PORT, return the auth code."""
    result: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urllib.parse.urlsplit(self.path)
            qs = urllib.parse.parse_qs(parsed.query)
            if parsed.path == "/callback" and "code" in qs:
                result["code"] = qs["code"][0]
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(_AUTH_HTML)
            else:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Authorization failed: missing code.")
            threading.Thread(target=self.server.shutdown, daemon=True).start()

        def log_message(self, format, *args):  # silence
            pass

    server = HTTPServer(("127.0.0.1", AUTH_PORT), Handler)
    try:
        server.timeout = timeout
        server.handle_request()
        server.serve_forever()
    finally:
        server.server_close()
    return result.get("code", "")


def open_browser(url: str) -> bool:
    try:
        return webbrowser.open(url)
    except Exception:
        return False


def complete_auth(client_id: str, verifier: str) -> dict:
    """Run the full interactive PKCE flow; returns the token JSON."""
    code = run_callback_server()
    if not code:
        raise RuntimeError("No authorization code received (timed out?).")
    return exchange_code(client_id, code, verifier, REDIRECT_URI)

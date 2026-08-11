"""The spotify-dock daemon: poll Spotify state, serve a local HTTP API.

Endpoints (127.0.0.1, default port 47555):
    GET  /health   -> {"ok": true, "version": "..."}
    GET  /state    -> full playback state JSON (see build_state)
    POST /control  -> {"action": "play"|"pause"|"next"|"previous"}

The extension polls /state every second; the daemon refreshes its view of
the account every `poll_interval` seconds.
"""

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__
from .api import SpotifyClient, SpotifyError, refresh_access_token
from .art import ART_PATH, art_key, fetch_art
from .config import DEFAULT_POLL, DEFAULT_PORT, load_config, token_expired
from .control import mpris_control, resolve_control

log = logging.getLogger("spotify-dock")


def build_state(raw: dict | None) -> dict:
    """Normalize a parsed /v1/me/player payload into the public state dict."""
    if not raw:
        return {
            "session_active": False,
            "playing": False,
            "track": "",
            "artist": "",
            "album": "",
            "art_key": "",
            "device": None,
            "connected": True,
        }
    item = raw.get("item") or {}
    track = item.get("name") or ""
    artists = ", ".join(a.get("name", "") for a in (item.get("artists") or []) if a.get("name"))
    album = (item.get("album") or {}).get("name") or ""
    return {
        "session_active": True,
        "playing": bool(raw.get("is_playing")),
        "track": track,
        "artist": artists,
        "album": album,
        "art_key": art_key(item),
        "device": raw.get("device"),
        "connected": True,
    }


class DockDaemon:
    def __init__(self, config_path=None, port: int | None = None,
                 poll_interval: float | None = None):
        from .config import CONFIG_PATH
        self.config_path = config_path or CONFIG_PATH
        self.cfg = load_config(self.config_path)
        self.port = port or self.cfg.get("port") or DEFAULT_PORT
        self.poll_interval = poll_interval or self.cfg.get("poll_interval") or DEFAULT_POLL
        self.product: str | None = self.cfg.get("product")
        self.state = build_state(None)
        self._last_art_key: str | None = None
        self._last_images: list = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._server = None

    # ---- token management ----
    def _ensure_token(self) -> str | None:
        token = self.cfg.get("access_token")
        if not token:
            return None
        if token_expired(self.cfg):
            try:
                fresh = refresh_access_token(self.cfg["client_id"], self.cfg["refresh_token"])
                self.cfg["access_token"] = fresh["access_token"]
                if "refresh_token" in fresh:
                    self.cfg["refresh_token"] = fresh["refresh_token"]
                self.cfg["token_expiry"] = time.time() + fresh.get("expires_in", 3600)
                from .config import save_config
                save_config(self.cfg, self.config_path)
                token = self.cfg["access_token"]
                log.info("refreshed access token")
            except SpotifyError as exc:
                log.error("token refresh failed: %s", exc)
                return None
        return token

    def _fetch_me(self, client: SpotifyClient) -> None:
        try:
            me = client.me()
            self.product = me.get("product") or self.product
            self.cfg["product"] = self.product
            from .config import save_config
            save_config(self.cfg, self.config_path)
        except SpotifyError as exc:
            log.warning("could not fetch profile: %s", exc)

    # ---- polling ----
    def poll_once(self) -> None:
        token = self._ensure_token()
        if not token:
            with self._lock:
                self.state = {**build_state(None), "connected": False}
            return
        client = SpotifyClient(token)
        try:
            status, raw = client.player()
            if status == 204:
                with self._lock:
                    self.state = build_state(None)
            elif status == 200:
                parsed = json.loads(raw) if raw else None
                images = ((parsed or {}).get("item") or {}).get("album", {}).get("images") or []
                with self._lock:
                    self._last_images = images
                    self.state = build_state(parsed)
                    self._maybe_fetch_art_locked()
            elif status == 401:
                # token rejected — force refresh next round
                self.cfg["token_expiry"] = 0
                log.warning("player API returned 401; will refresh token")
                with self._lock:
                    self.state = {**build_state(None), "connected": False}
            elif status == 429:
                log.warning("rate limited (429); backing off")
                time.sleep(min(self.poll_interval * 4, 30))
            else:
                log.warning("player API returned HTTP %s", status)
        except (SpotifyError, OSError, ValueError) as exc:
            log.error("poll failed: %s", exc)
            with self._lock:
                self.state = {**build_state(None), "connected": False}

    def _maybe_fetch_art_locked(self) -> None:
        cur_key = self.state.get("art_key", "")
        if cur_key and cur_key != self._last_art_key:
            self._last_art_key = cur_key
            url = self._last_images[0]["url"] if self._last_images else ""
            if url:
                fetch_art(url)

    # ---- public state (thread-safe) ----
    def get_state(self) -> dict:
        with self._lock:
            mode, reason = resolve_control(self.state, self.product or "")
            return {
                "ok": True,
                "version": __version__,
                "connected": self.state.get("connected", False),
                "session_active": self.state.get("session_active", False),
                "playing": self.state.get("playing", False),
                "track": self.state.get("track", ""),
                "artist": self.state.get("artist", ""),
                "album": self.state.get("album", ""),
                "art_key": self.state.get("art_key", ""),
                "art_path": ART_PATH if self.state.get("session_active") else "",
                "device": self.state.get("device"),
                "device_name": (self.state.get("device") or {}).get("name", ""),
                "control": mode,
                "control_reason": reason,
                "product": self.product,
            }

    def handle_control(self, action: str) -> dict:
        if action not in ("play", "pause", "next", "previous"):
            return {"ok": False, "error": f"unknown action: {action}"}
        with self._lock:
            state = dict(self.state)
        mode, reason = resolve_control(state, self.product or "")
        if mode == "none":
            return {"ok": False, "method": None, "error": reason or "unavailable"}
        if mode == "local":
            ok = mpris_control(action)
            return {"ok": ok, "method": "mpris",
                    "error": None if ok else "local player control failed"}
        # remote (premium)
        token = self._ensure_token()
        if not token:
            return {"ok": False, "method": "webapi", "error": "auth unavailable"}
        try:
            status, _ = SpotifyClient(token).control(action)
            ok = status in (200, 204)
            return {"ok": ok, "method": "webapi",
                    "error": None if ok else f"Spotify API HTTP {status}"}
        except SpotifyError as exc:
            return {"ok": False, "method": "webapi", "error": str(exc)}

    # ---- server ----
    def _handler_factory(self):
        daemon = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass

            def _send_json(self, obj, status=200):
                raw = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                if self.path.startswith("/health"):
                    self._send_json({"ok": True, "version": __version__})
                elif self.path.startswith("/state"):
                    self._send_json(daemon.get_state())
                else:
                    self._send_json({"ok": False, "error": "not found"}, 404)

            def do_POST(self):
                if self.path.startswith("/control"):
                    try:
                        length = int(self.headers.get("Content-Length", 0))
                        payload = json.loads(self.rfile.read(length) or b"{}")
                        action = payload.get("action", "")
                        self._send_json(daemon.handle_control(action))
                    except (ValueError, json.JSONDecodeError):
                        self._send_json({"ok": False, "error": "bad request"}, 400)
                else:
                    self._send_json({"ok": False, "error": "not found"}, 404)

        return Handler

    # ---- lifecycle ----
    def run(self) -> None:
        handler = self._handler_factory()
        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), handler)
        log.info("spotify-dock %s listening on 127.0.0.1:%s", __version__, self.port)
        threading.Thread(target=self._poll_loop, daemon=True).start()
        self._server.serve_forever()

    def _poll_loop(self) -> None:
        # initial poll + profile
        token = self._ensure_token()
        if token:
            self._fetch_me(SpotifyClient(token))
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception as exc:  # never let the loop die
                log.error("poll loop error: %s", exc)
            self._stop.wait(self.poll_interval)

    def stop(self) -> None:
        self._stop.set()
        if self._server:
            self._server.shutdown()
            self._server.server_close()

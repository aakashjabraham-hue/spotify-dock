"""Minimal Spotify Web API client (stdlib only)."""

import json
import urllib.error
import urllib.parse
import urllib.request

API_BASE = "https://api.spotify.com/v1"
TOKEN_URL = "https://accounts.spotify.com/api/token"
_USER_AGENT = "spotify-dock/0.1"


class SpotifyError(Exception):
    def __init__(self, status: int, body: bytes = b"", message: str = ""):
        self.status = status
        self.body = body
        self.message = message or body.decode("utf-8", "replace")[:200]
        super().__init__(f"Spotify API HTTP {status}: {self.message}")


def _request(url, method="GET", headers=None, body=None, timeout=15):
    req = urllib.request.Request(url, method=method, headers=headers or {}, data=body)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except urllib.error.URLError:
        raise


def refresh_access_token(client_id: str, refresh_token: str) -> dict:
    """POST /api/token with grant_type=refresh_token. Returns raw JSON."""
    data = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": client_id,
        }
    ).encode()
    status, raw = _request(
        TOKEN_URL,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=data,
    )
    if status != 200:
        raise SpotifyError(status, raw)
    return json.loads(raw)


def exchange_code(client_id: str, code: str, verifier: str, redirect_uri: str) -> dict:
    """PKCE authorization-code exchange. Returns raw JSON with tokens."""
    data = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": verifier,
        }
    ).encode()
    status, raw = _request(
        TOKEN_URL,
        method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        body=data,
    )
    if status != 200:
        raise SpotifyError(status, raw)
    return json.loads(raw)


class SpotifyClient:
    """Thin wrapper over the Web API. Player reads work on Free accounts;
    player writes require Premium (Spotify-side restriction)."""

    def __init__(self, access_token: str):
        self.access_token = access_token

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.access_token}",
            "User-Agent": _USER_AGENT,
        }

    def me(self):
        """GET /v1/me — returns (status, parsed dict). product field: free/premium."""
        status, raw = _request(API_BASE + "/me", headers=self._headers())
        if status != 200:
            raise SpotifyError(status, raw)
        return json.loads(raw)

    def player(self):
        """GET /v1/me/player — 204 means no active playback session."""
        status, raw = _request(API_BASE + "/me/player", headers=self._headers())
        return status, raw

    def control(self, action: str):
        """play/pause are PUT, next/previous are POST. Returns (status, raw)."""
        path = {
            "play": "/me/player/play",
            "pause": "/me/player/pause",
            "next": "/me/player/next",
            "previous": "/me/player/previous",
        }[action]
        method = "PUT" if action in ("play", "pause") else "POST"
        status, raw = _request(API_BASE + path, method=method, headers=self._headers())
        return status, raw

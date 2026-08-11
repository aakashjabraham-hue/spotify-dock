"""Hermetic tests for spotify-dock core (no network, no Spotify account)."""

import base64
import hashlib
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from spotify_dock import auth, control
from spotify_dock.api import SpotifyClient, SpotifyError, refresh_access_token
from spotify_dock.art import art_key
from spotify_dock.config import load_config, save_config
from spotify_dock.daemon import DockDaemon, build_state

PLAYER_PAYLOAD = {
    "is_playing": True,
    "device": {"id": "dev-1", "name": "AJs-Phone", "type": "Smartphone", "is_active": True},
    "item": {
        "id": "track1",
        "name": "Test Track",
        "artists": [{"name": "Artist One"}, {"name": "Artist Two"}],
        "album": {
            "name": "Test Album",
            "images": [{"url": "https://i.scdn.co/image/abc", "width": 640}],
        },
    },
}

LOCAL_PAYLOAD = {
    **PLAYER_PAYLOAD,
    "device": {"id": "dev-2", "name": "ajs-computer", "type": "Computer", "is_active": True},
}


# ---------------------------------------------------------------- config --
def test_config_roundtrip(tmp_path):
    path = str(tmp_path / "config.json")
    save_config({"client_id": "abc123", "access_token": "tok"}, path)
    assert load_config(path) == {"client_id": "abc123", "access_token": "tok"}
    assert load_config(str(tmp_path / "missing.json")) == {}


# ---------------------------------------------------------------- state ----
def test_build_state_playing():
    s = build_state(PLAYER_PAYLOAD)
    assert s["session_active"] is True
    assert s["playing"] is True
    assert s["track"] == "Test Track"
    assert s["artist"] == "Artist One, Artist Two"
    assert s["album"] == "Test Album"
    assert s["art_key"] == "track1|https://i.scdn.co/image/abc"
    assert s["device"]["name"] == "AJs-Phone"


def test_build_state_paused():
    payload = {**PLAYER_PAYLOAD, "is_playing": False}
    assert build_state(payload)["playing"] is False
    assert build_state(payload)["session_active"] is True


def test_build_state_empty():
    s = build_state(None)
    assert s["session_active"] is False
    assert s["playing"] is False
    assert s["track"] == ""
    assert s["art_key"] == ""


def test_build_state_no_item():
    assert build_state({"is_playing": False})["session_active"] is True
    assert build_state({"is_playing": False})["track"] == ""


# -------------------------------------------------------- control chain ----
def test_resolve_none_without_session(monkeypatch):
    monkeypatch.setattr(control, "local_spotify_running", lambda: True)
    mode, reason = control.resolve_control(build_state(None), "premium")
    assert mode == "none" and reason == "no_active_session"


def test_resolve_local_when_computer_device(monkeypatch):
    monkeypatch.setattr(control, "local_spotify_running", lambda: True)
    mode, reason = control.resolve_control(build_state(LOCAL_PAYLOAD), "free")
    assert mode == "local" and reason is None


def test_resolve_remote_premium(monkeypatch):
    monkeypatch.setattr(control, "local_spotify_running", lambda: False)
    mode, reason = control.resolve_control(build_state(PLAYER_PAYLOAD), "premium")
    assert mode == "remote" and reason is None


def test_resolve_remote_free_blocked(monkeypatch):
    monkeypatch.setattr(control, "local_spotify_running", lambda: False)
    mode, reason = control.resolve_control(build_state(PLAYER_PAYLOAD), "free")
    assert mode == "none" and reason == "premium_required"


def test_resolve_phone_device_not_local_even_if_app_running(monkeypatch):
    monkeypatch.setattr(control, "local_spotify_running", lambda: True)
    mode, reason = control.resolve_control(build_state(PLAYER_PAYLOAD), "free")
    assert mode == "none" and reason == "premium_required"


# ------------------------------------------------------------ art cache ----
def test_art_key_stable():
    assert art_key(PLAYER_PAYLOAD["item"]) == "track1|https://i.scdn.co/image/abc"
    assert art_key({}) == ""
    assert art_key(None) == ""


# ---------------------------------------------------------------- auth -----
def test_pkce_challenge_known_vector():
    verifier = "x".join(str(i) for i in range(20))  # deterministic
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert auth.make_challenge(verifier) == expected
    assert auth.make_verifier() != auth.make_verifier()


# ---------------------------------------------------------------- api ------
def test_refresh_token_ok(monkeypatch):
    from spotify_dock import api
    monkeypatch.setattr(api, "_request",
                        lambda *a, **k: (200, json.dumps(
                            {"access_token": "new", "expires_in": 3600}).encode()))
    out = refresh_access_token("cid", "rt")
    assert out["access_token"] == "new"


def test_refresh_token_error(monkeypatch):
    from spotify_dock import api
    monkeypatch.setattr(api, "_request", lambda *a, **k: (400, b"bad"))
    with pytest.raises(SpotifyError):
        refresh_access_token("cid", "rt")


def test_control_method_mapping(monkeypatch):
    from spotify_dock import api
    calls = []
    def fake_request(url, method="GET", headers=None, body=None, timeout=15):
        calls.append((url, method))
        return (204, b"")
    monkeypatch.setattr(api, "_request", fake_request)
    client = SpotifyClient("tok")
    client.control("play")
    client.control("pause")
    client.control("next")
    client.control("previous")
    assert calls[0][1] == "PUT" and calls[0][0].endswith("/play")
    assert calls[1][1] == "PUT" and calls[1][0].endswith("/pause")
    assert calls[2][1] == "POST" and calls[2][0].endswith("/next")
    assert calls[3][1] == "POST" and calls[3][0].endswith("/previous")


# ---------------------------------------------------------------- daemon ---
def _make_daemon(tmp_path, payload, product):
    daemon = DockDaemon(config_path=str(tmp_path / "config.json"), port=0)
    daemon.state = build_state(payload)
    daemon.product = product
    return daemon


def test_handle_control_local_mpris(tmp_path, monkeypatch):
    from spotify_dock import daemon as daemon_mod
    monkeypatch.setattr(control, "local_spotify_running", lambda: True)
    monkeypatch.setattr(daemon_mod, "mpris_control", lambda action: True)
    daemon = _make_daemon(tmp_path, LOCAL_PAYLOAD, "free")
    out = daemon.handle_control("next")
    assert out == {"ok": True, "method": "mpris", "error": None}


def test_handle_control_remote_free_blocked(tmp_path, monkeypatch):
    monkeypatch.setattr(control, "local_spotify_running", lambda: False)
    daemon = _make_daemon(tmp_path, PLAYER_PAYLOAD, "free")
    out = daemon.handle_control("pause")
    assert out["ok"] is False and out["error"] == "premium_required"


def test_handle_control_remote_premium(tmp_path, monkeypatch):
    monkeypatch.setattr(control, "local_spotify_running", lambda: False)
    from spotify_dock import api
    monkeypatch.setattr(api.SpotifyClient, "control", lambda self, a: (204, b""))
    daemon = _make_daemon(tmp_path, PLAYER_PAYLOAD, "premium")
    monkeypatch.setattr(daemon, "_ensure_token", lambda: "tok")
    out = daemon.handle_control("pause")
    assert out == {"ok": True, "method": "webapi", "error": None}


def test_handle_control_no_session(tmp_path):
    daemon = _make_daemon(tmp_path, None, "premium")
    out = daemon.handle_control("play")
    assert out["ok"] is False and out["error"] == "no_active_session"


def test_handle_control_unknown_action(tmp_path):
    daemon = _make_daemon(tmp_path, PLAYER_PAYLOAD, "free")
    assert daemon.handle_control("shuffle")["ok"] is False


# ------------------------------------------------------------ http api -----
def test_http_state_and_control(tmp_path, monkeypatch):
    monkeypatch.setattr(control, "local_spotify_running", lambda: False)
    daemon = _make_daemon(tmp_path, PLAYER_PAYLOAD, "free")
    handler = daemon._handler_factory()
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{port}"
        state = json.loads(urllib.request.urlopen(f"{base}/state", timeout=5).read())
        assert state["ok"] is True
        assert state["session_active"] is True
        assert state["track"] == "Test Track"
        assert state["control"] == "none"
        assert state["control_reason"] == "premium_required"
        assert state["product"] == "free"

        req = urllib.request.Request(
            f"{base}/control", method="POST",
            data=json.dumps({"action": "next"}).encode(),
            headers={"Content-Type": "application/json"})
        resp = json.loads(urllib.request.urlopen(req, timeout=5).read())
        assert resp["error"] == "premium_required"

        health = json.loads(urllib.request.urlopen(f"{base}/health", timeout=5).read())
        assert health["ok"] is True
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

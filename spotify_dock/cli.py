"""spotify-dock CLI: setup wizard, install/uninstall, update, status, daemon.

Matches the project conventions: one-liner install (install.sh -> `setup`),
keep/change credential wizard, `version` subcommand, self-update via codeload.
"""

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request

from . import __version__
from .auth import auth_url, complete_auth, make_verifier, open_browser
from .config import CONFIG_PATH, has_config, load_config, save_config

REPO = "aakashjabraham-hue/spotify-dock"
BRANCH = "master"
EXT_UUID = "spotify-dock@aakashjabraham-hue"
EXT_DIR = os.path.expanduser(f"~/.local/share/gnome-shell/extensions/{EXT_UUID}")
INSTALL_DIR = os.path.expanduser("~/.local/share/spotify-dock")
UNIT_PATH = os.path.expanduser("~/.config/systemd/user/spotify-dock.service")

_G = "\033[0;32m"; _Y = "\033[1;33m"; _R = "\033[0;31m"; _B = "\033[1m"; _N = "\033[0m"
ok = lambda s: print(f"{_G}  ✓{_N} {s}")
warn = lambda s: print(f"{_Y}  ⚠{_N} {s}")
fail = lambda s: print(f"{_R}  ✗{_N} {s}")


def _extension_source_dir() -> str:
    """extension/ lives next to the spotify_dock package."""
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "extension")


def _curl(url: str, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args],
                          capture_output=True, text=True, timeout=30)


def _install_extension() -> None:
    src = _extension_source_dir()
    if not os.path.isdir(src):
        raise RuntimeError(f"extension source not found: {src}")
    if os.path.isdir(EXT_DIR):
        shutil.rmtree(EXT_DIR)
    shutil.copytree(src, EXT_DIR)
    ok(f"extension installed ({EXT_UUID})")


def _install_unit() -> None:
    os.makedirs(os.path.dirname(UNIT_PATH), exist_ok=True)
    unit = f"""[Unit]
Description=Spotify Dock daemon (top-bar playback controller)
After=default.target

[Service]
ExecStart={os.path.expanduser('~/.local/bin/spotify-dock')} daemon
Restart=on-failure
RestartSec=3

[Install]
WantedBy=default.target
"""
    with open(UNIT_PATH, "w", encoding="utf-8") as fh:
        fh.write(unit)
    _systemctl("daemon-reload")
    _systemctl("enable", "--now", "spotify-dock.service")
    ok("daemon service enabled + started (systemd user unit)")


def _enable_extension() -> None:
    try:
        out = subprocess.run(["gsettings", "get", "org.gnome.shell", "enabled-extensions"],
                             capture_output=True, text=True, timeout=10)
        current = ast.literal_eval(out.stdout.strip()) if out.returncode == 0 else []
        if EXT_UUID not in current:
            current.append(EXT_UUID)
            subprocess.run(["gsettings", "set", "org.gnome.shell", "enabled-extensions",
                            str(current)], check=True, timeout=10)
        ok("extension enabled in GNOME Shell")
    except Exception as exc:
        warn(f"could not auto-enable extension: {exc}")


def _daemon_health() -> dict:
    try:
        raw = _curl(f"http://127.0.0.1:{_daemon_port()}/health", timeout=3)
        return json.loads(raw)
    except Exception:
        return {}


def _daemon_port() -> int:
    return int(load_config().get("port") or 47555)


def _ask_client_id() -> str:
    print(f"\n{_B}Spotify Developer app{_N} — one-time setup (2 min):")
    print("  1. Open https://developer.spotify.com/dashboard and log in")
    print("  2. Create app (any name, e.g. spotify-dock)")
    print("  3. Redirect URI:  http://127.0.0.1:47556/callback")
    print("  4. Copy the Client ID from the app page\n")
    while True:
        cid = input(f"{_B}Paste your Client ID{_N}: ").strip()
        if not cid:
            continue
        if re.fullmatch(r"[0-9a-fA-F]{10,64}", cid):
            return cid
        if input("  That doesn't look like a Client ID — use it anyway? [y/N] ").strip().lower() == "y":
            return cid


def _auth_flow(cfg: dict) -> None:
    verifier = make_verifier()
    url = auth_url(cfg["client_id"], verifier)
    print(f"\n{_B}Authorizing with Spotify…{_N}")
    if not open_browser(url):
        print(f"  Browser didn't open — paste this URL manually:\n  {url}")
    print("  Waiting for the browser callback…")
    tokens = complete_auth(cfg["client_id"], verifier)
    cfg["access_token"] = tokens["access_token"]
    cfg["refresh_token"] = tokens.get("refresh_token", cfg.get("refresh_token", ""))
    cfg["token_expiry"] = time.time() + tokens.get("expires_in", 3600)
    save_config(cfg)
    ok("authorized")


def _fetch_profile(cfg: dict) -> tuple[str, str]:
    from .api import SpotifyClient, SpotifyError
    try:
        me = SpotifyClient(cfg["access_token"]).me()
        name = me.get("display_name") or me.get("id") or "unknown"
        return name, me.get("product", "unknown")
    except (SpotifyError, OSError, KeyError):
        return "unknown", cfg.get("product", "unknown")


def cmd_setup(args) -> int:
    print(f"\n{_B}🎧 Spotify Dock {__version__} — setup{_N}")
    cfg = load_config()
    if has_config():
        choice = input(f"{_Y}Existing credentials found{_N} — keep them or change? [K/c] ").strip().lower()
        if choice != "c":
            ok("keeping existing credentials")
        else:
            cfg = {"port": cfg.get("port", 47555), "poll_interval": cfg.get("poll_interval", 3.0)}
            cfg["client_id"] = _ask_client_id()
            _auth_flow(cfg)
    else:
        cfg = {"port": cfg.get("port", 47555), "poll_interval": cfg.get("poll_interval", 3.0)}
        cfg["client_id"] = _ask_client_id()
        _auth_flow(cfg)

    name, product = _fetch_profile(cfg)
    cfg["product"] = product
    save_config(cfg)
    ok(f"logged in as {_B}{name}{_N} ({product} account)")
    if product != "premium":
        warn("Free account: local playback controls work; remote-device control is Spotify-Premium-only")

    print(f"\n{_B}Installing…{_N}")
    _install_extension()
    _install_unit()
    _enable_extension()
    print(f"\n{_G}✔{_N} {_B}Done!{_N} Restart GNOME Shell (Alt+F2 → {_B}restart{_N}, or log out/in),")
    print("  then play something on Spotify — the icon appears in the top bar. 🎧")
    return 0


def cmd_install(args) -> int:
    _install_extension()
    _install_unit()
    _enable_extension()
    print(f"\n{_G}✔{_N} Installed. Restart GNOME Shell (Alt+F2 → restart) to see the icon.")
    return 0


def cmd_uninstall(args) -> int:
    print(f"\n{_B}Uninstalling Spotify Dock…{_N}")
    _systemctl("disable", "--now", "spotify-dock.service")
    for path, label in ((UNIT_PATH, "systemd unit"), (EXT_DIR, "extension")):
        if os.path.exists(path):
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.unlink(path)
            ok(f"removed {label}")
    try:
        out = subprocess.run(["gsettings", "get", "org.gnome.shell", "enabled-extensions"],
                             capture_output=True, text=True, timeout=10)
        current = ast.literal_eval(out.stdout.strip()) if out.returncode == 0 else []
        if EXT_UUID in current:
            current.remove(EXT_UUID)
            subprocess.run(["gsettings", "set", "org.gnome.shell", "enabled-extensions",
                            str(current)], check=True, timeout=10)
            ok("removed from enabled extensions")
    except Exception:
        pass
    if os.path.exists(CONFIG_PATH) and input("  Remove saved Spotify credentials too? [y/N] ").strip().lower() == "y":
        os.unlink(CONFIG_PATH)
        ok("credentials removed")
    print(f"\n{_G}✔{_N} Uninstalled.")
    return 0


def _fetch_remote_version() -> str:
    url = f"https://raw.githubusercontent.com/{REPO}/{BRANCH}/spotify_dock/__init__.py?ts={int(time.time())}"
    raw = _curl(url).decode("utf-8", "replace")
    m = re.search(r'__version__\s*=\s*"([^"]+)"', raw)
    return m.group(1) if m else ""


def cmd_update(args) -> int:
    print(f"\n{_B}Spotify Dock update{_N} — local {__version__}")
    remote = _fetch_remote_version()
    if not remote:
        fail("could not fetch latest version — are you online?")
        return 1
    if remote == __version__:
        ok(f"already up to date ({remote})")
        return 0
    print(f"  {__version__} → {_B}{remote}{_N}")
    import tarfile
    tmp = f"/tmp/spotify-dock-update-{int(time.time())}"
    tarball = f"https://codeload.github.com/{REPO}/tar.gz/refs/heads/{BRANCH}?ts={int(time.time())}"
    raw = _curl(tarball, timeout=60)
    os.makedirs(tmp, exist_ok=True)
    archive = os.path.join(tmp, "dl.tar.gz")
    with open(archive, "wb") as fh:
        fh.write(raw)
    with tarfile.open(archive) as tf:
        tf.extractall(tmp)
    src = os.path.join(tmp, f"spotify-dock-{BRANCH}")
    if not os.path.isdir(src):
        src = [d for d in os.listdir(tmp) if d.startswith("spotify-dock-")][0]
        src = os.path.join(tmp, src)
    new_dir = os.path.join(INSTALL_DIR, "current.new")
    shutil.rmtree(new_dir, ignore_errors=True)
    shutil.copytree(src, new_dir)
    old_dir = os.path.join(INSTALL_DIR, "current.old")
    shutil.rmtree(old_dir, ignore_errors=True)
    if os.path.isdir(os.path.join(INSTALL_DIR, "current")):
        os.rename(os.path.join(INSTALL_DIR, "current"), old_dir)
    os.rename(new_dir, os.path.join(INSTALL_DIR, "current"))
    shutil.rmtree(old_dir, ignore_errors=True)
    shutil.rmtree(tmp, ignore_errors=True)
    ok(f"updated to {remote}")
    _install_extension()
    _systemctl("restart", "spotify-dock.service")
    ok("daemon restarted")
    return 0


def cmd_status(args) -> int:
    print(f"\n{_B}Spotify Dock {__version__}{_N}")
    print(f"  config:     {'present' if has_config() else _Y + 'missing (run spotify-dock setup)' + _N}")
    cfg = load_config()
    if has_config():
        name, product = _fetch_profile(cfg) if cfg.get("access_token") else ("?", "?")
        print(f"  account:    {name} ({product})")
    health = _daemon_health()
    if health.get("ok"):
        print(f"  daemon:     {_G}running{_N} (port {_daemon_port()})")
        try:
            state = json.loads(_curl(f"http://127.0.0.1:{_daemon_port()}/state", timeout=3))
            if state.get("session_active"):
                print(f"  now playing: {_B}{state.get('track')}{_N} — {state.get('artist')}  ({state.get('device_name')})")
                print(f"  control:    {state.get('control')}"
                      + (f" ({state.get('control_reason')})" if state.get("control_reason") else ""))
            else:
                print(f"  now playing: {_Y}nothing{_N} — icon hidden")
        except Exception:
            pass
    else:
        print(f"  daemon:     {_R}not running{_N} (start with `spotify-dock daemon` or systemctl --user start spotify-dock)")
    print(f"  extension:  {'installed' if os.path.isdir(EXT_DIR) else _R + 'missing' + _N}")
    return 0


def cmd_daemon(args) -> int:
    import logging
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    from .daemon import DockDaemon
    daemon = DockDaemon(port=args.port, poll_interval=args.poll)
    daemon.run()
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="spotify-dock", description="Spotify playback controller for the GNOME top bar")
    parser.add_argument("--version", action="version", version=f"spotify-dock {__version__}")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("setup", help="auth wizard + install daemon & extension")
    sub.add_parser("install", help="install daemon & extension (no auth)")
    sub.add_parser("uninstall", help="remove daemon & extension")
    sub.add_parser("update", help="self-update to the latest version")
    sub.add_parser("status", help="show config/account/daemon/extension state")
    sub.add_parser("version", help="print version")
    d = sub.add_parser("daemon", help="run the daemon in the foreground")
    d.add_argument("--port", type=int, default=None)
    d.add_argument("--poll", type=float, default=None, help="poll interval seconds")
    d.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    handlers = {
        "setup": cmd_setup, "install": cmd_install, "uninstall": cmd_uninstall,
        "update": cmd_update, "status": cmd_status, "version": lambda a: print(__version__) or 0,
        "daemon": cmd_daemon,
    }
    if args.command is None:
        parser.print_help()
        return 0
    return handlers[args.command](args) or 0


if __name__ == "__main__":
    sys.exit(main())

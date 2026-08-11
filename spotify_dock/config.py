"""Config + path handling for spotify-dock.

Config lives in ~/.config/spotify-dock/config.json (0600):
    {
      "client_id": "...",
      "access_token": "...",
      "refresh_token": "...",
      "token_expiry": 1730000000.0,   # epoch seconds
      "port": 47555,
      "poll_interval": 3.0
    }
"""

import json
import os
import stat
import time

CONFIG_DIR = os.path.expanduser("~/.config/spotify-dock")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")
CACHE_DIR = os.path.expanduser("~/.cache/spotify-dock")
ART_PATH = os.path.join(CACHE_DIR, "art.jpg")
DEFAULT_PORT = 47555
DEFAULT_POLL = 3.0


def load_config(path: str = CONFIG_PATH) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return {}
        return data
    except (OSError, json.JSONDecodeError):
        return {}


def save_config(cfg: dict, path: str = CONFIG_PATH) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, indent=2)
    os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)
    os.replace(tmp, path)


def has_config(path: str = CONFIG_PATH) -> bool:
    return os.path.isfile(path) and bool(load_config(path).get("client_id"))


def token_expired(cfg: dict, slack: float = 60.0) -> bool:
    expiry = cfg.get("token_expiry", 0)
    return time.time() >= (expiry - slack)


def ensure_cache_dir() -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)

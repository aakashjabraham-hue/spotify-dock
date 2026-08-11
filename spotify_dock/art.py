"""Album art caching: download the current cover to ~/.cache/spotify-dock/art.jpg."""

import os
import tempfile
import urllib.request

from .config import ART_PATH, CACHE_DIR, ensure_cache_dir


def art_key(track: dict | None) -> str:
    """Stable key so callers can skip reloading art when nothing changed."""
    if not track:
        return ""
    image = ""
    images = track.get("album", {}).get("images") or []
    if images:
        image = images[0].get("url", "")
    return f"{track.get('id') or ''}|{image}"


def fetch_art(url: str, dest: str = ART_PATH) -> str | None:
    """Download album art to dest (atomic replace). Returns dest or None."""
    if not url:
        return None
    ensure_cache_dir()
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": "spotify-dock/0.1"}
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
        ext = ".jpg"
        ctype = resp.headers.get("Content-Type", "")
        if "png" in ctype:
            ext = ".png"
        fd, tmp = tempfile.mkstemp(prefix="art-", suffix=ext, dir=CACHE_DIR)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(raw)
            os.replace(tmp, dest)
        except OSError:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        return dest
    except OSError:
        return None


def art_exists() -> bool:
    return os.path.isfile(ART_PATH)

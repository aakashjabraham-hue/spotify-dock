"""Control chain: figure out HOW a play/pause/skip command should be sent.

Priority:
1. Active device is this computer (local Spotify app)  -> MPRIS via playerctl
   (works on Free accounts — no Premium needed for local control)
2. Active device is elsewhere and account is Premium   -> Spotify Web API
3. Anything else                                       -> blocked (Premium wall)

On Free accounts the Web API refuses playback control for remote devices,
so we never attempt it — the daemon reports `none` + `premium_required` and
the extension greys the buttons with a note.
"""

import socket
import subprocess

_PLAYERCTL = "playerctl"


def local_spotify_running() -> bool:
    """True if a Spotify MPRIS player exists on the session bus (any state)."""
    try:
        out = subprocess.run(
            [_PLAYERCTL, "--player=spotify", "status"],
            capture_output=True, text=True, timeout=5,
        )
        return out.returncode == 0 and out.stdout.strip() in (
            "Playing", "Paused", "Stopped",
        )
    except (OSError, subprocess.SubprocessError):
        return False


def mpris_control(action: str) -> bool:
    """Send a control command to the local Spotify app via MPRIS."""
    try:
        out = subprocess.run(
            [_PLAYERCTL, "--player=spotify", action],
            capture_output=True, timeout=5,
        )
        return out.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def device_is_local(device: dict | None) -> bool:
    """Best-effort: is this Web API device this computer?"""
    if not device:
        return False
    if device.get("type") == "Computer":
        return True
    name = (device.get("name") or "").lower()
    host = socket.gethostname().lower()
    return bool(host) and (name == host or name.startswith(host))


def resolve_control(state: dict, product: str) -> tuple[str, str | None]:
    """Return (mode, reason). mode: 'local' | 'remote' | 'none'."""
    if not state.get("session_active"):
        return "none", "no_active_session"
    if local_spotify_running() and device_is_local(state.get("device")):
        return "local", None
    if product == "premium":
        return "remote", None
    return "none", "premium_required"

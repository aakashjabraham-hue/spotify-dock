# 🎧 Spotify Dock

A Spotify playback controller living in the GNOME top bar.

A small Spotify icon appears in the top panel **only while something is playing on your account** (any device — this computer, your phone, your TV). Click it for a dropdown with the album art, track title, and skip-back / play-pause / skip-forward controls.

![Layout: top-bar icon → dropdown with album art left, controls right]

## Features

- **Dynamic panel icon** — appears only when playback is active on your account, hides when nothing is playing
- **Dropdown controls** — album art on the left; skip back, play/pause, skip forward on the right; live-updating track title and artist
- **Works across devices** — state comes from the Spotify Web API, so it shows what's playing anywhere on your account, even if the local app is closed
- **Free-account friendly** — local playback is controlled directly through the Spotify app (MPRIS), which needs no Premium
- **One-liner install** — `curl | bash`, browser-based auth, systemd daemon, extension auto-enabled

## Requirements

- GNOME Shell 45+ (built and tested on GNOME 50)
- Python 3 (system)
- `playerctl` (for local control; usually preinstalled — `sudo apt install playerctl`)
- The Spotify desktop app (Flatpak, `.deb`, or snap) for local playback control
- A Spotify account + a free **Spotify Developer app** (2 minutes — see below)

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/aakashjabraham-hue/spotify-dock/master/install.sh | bash
```

The installer:

1. Downloads the latest release into `~/.local/share/spotify-dock/`
2. Installs the `spotify-dock` command into `~/.local/bin/`
3. Copies the GNOME Shell extension into place
4. Runs the setup wizard: paste your Spotify Client ID → authorize in the browser → daemon starts automatically

After setup, restart GNOME Shell (**Alt+F2 → `restart`** on Wayland, or log out/in), then play something on Spotify. The icon appears.

### Getting a Spotify Client ID (one-time, ~2 min)

1. Go to https://developer.spotify.com/dashboard and **log in** with your Spotify account
2. Click **Create app** — any name (e.g. `spotify-dock`); description optional
3. Under **Redirect URIs**, add exactly: `http://127.0.0.1:47556/callback`
4. Click **Save**, open the app, and copy the **Client ID** (the long hex string)

Then paste it when `spotify-dock setup` asks. That's it — no client secret needed (PKCE flow).

## How it works

```
┌──────────────────────────┐     HTTP 127.0.0.1:47555      ┌──────────────────────┐
│  GNOME Shell extension   │ ◄────────────────────────────► │  spotify-dock daemon │
│  panel icon + dropdown   │   /state  /control  /health    │  (systemd user unit) │
└──────────────────────────┘                                 └──────────┬───────────┘
                                                                       │ Spotify Web API
                                                          ┌────────────▼────────────┐
                                                          │  your Spotify account   │
                                                          │  (any active device)    │
                                                          └─────────────────────────┘
```

- The **daemon** (Python, stdlib only) holds your OAuth token, polls `GET /v1/me/player` every 3 s, caches album art to `~/.cache/spotify-dock/`, and exposes a tiny local HTTP API.
- The **extension** polls `/state` every second. When there's no active playback session it hides the icon entirely.
- **Control chain** (what happens when you press a button):
  1. Active device is **this computer** → command goes to the local Spotify app via `playerctl`/MPRIS. Works on Free accounts.
  2. Active device is **another device** → command goes to the Web API. This is a Premium-only feature on Spotify's side; on Free accounts the buttons show *"Remote control needs Spotify Premium"* (and start working automatically if you ever upgrade).
  3. No active session → buttons are disabled.

## Commands

```bash
spotify-dock setup      # auth wizard + install (rerun to change credentials)
spotify-dock status     # config, auth, daemon, extension state
spotify-dock update     # self-update to the latest version
spotify-dock uninstall  # remove daemon + extension (+ config, optional)
spotify-dock daemon     # run the daemon in the foreground (debugging)
spotify-dock version    # print version
```

## Troubleshooting

- **Icon never appears** — `spotify-dock status` to confirm the daemon is running and authorized; play something on any device.
- **"Remote control needs Spotify Premium"** — that's Spotify's API restriction for Free accounts. Local playback (Spotify open on this computer) controls fine.
- **Buttons greyed out** — no active playback session; start something on any device.
- **After installing the extension** the icon needs a GNOME Shell restart (Wayland): Alt+F2 → `restart`.

## Development

```bash
git clone https://github.com/aakashjabraham-hue/spotify-dock
cd spotify-dock
python3 -m pytest tests/          # run the test suite
python3 -m spotify_dock daemon    # run daemon without systemd
```

Layout: `spotify_dock/` — daemon + CLI · `extension/` — GNOME Shell extension · `install.sh` — one-liner installer.

## License

MIT

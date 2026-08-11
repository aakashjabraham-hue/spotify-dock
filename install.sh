#!/usr/bin/env bash
# Spotify Dock — one-liner installer
# Downloads the latest version, installs the daemon + GNOME extension, then runs setup.
set -euo pipefail

REPO="aakashjabraham-hue/spotify-dock"
BRANCH="master"
DEST="${HOME}/.local/share/spotify-dock"
BIN="${HOME}/.local/bin"
SHIM="${BIN}/spotify-dock"
EXT_UUID="spotify-dock@aakashjabraham-hue"
EXT_DIR="${HOME}/.local/share/gnome-shell/extensions/${EXT_UUID}"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BOLD='\033[1m'; NC='\033[0m'
ok()   { printf "${GREEN}  ✓${NC} %s\n" "$1"; }
warn() { printf "${YELLOW}  ⚠${NC} %s\n" "$1"; }
fail() { printf "${RED}  ✗${NC} %s\n" "$1"; exit 1; }

echo -e "${BOLD}🎧 Spotify Dock — install${NC}"
mkdir -p "${DEST}" "${BIN}"

# ---- 1. Download latest tarball (cache-busted) ----
echo -e "\n${BOLD}1/4${NC} Downloading latest version…"
TARBALL="https://codeload.github.com/${REPO}/tar.gz/refs/heads/${BRANCH}?ts=$(date +%s)"
TMP="$(mktemp -d)"
curl -fsSL -H "Cache-Control: no-cache" "${TARBALL}" -o "${TMP}/spotify-dock.tar.gz" || fail "Download failed — are you online?"
tar -xzf "${TMP}/spotify-dock.tar.gz" -C "${TMP}"
SRC="${TMP}/spotify-dock-${BRANCH}"
[ -d "${SRC}" ] || SRC="$(find "${TMP}" -maxdepth 1 -type d -name 'spotify-dock-*' | head -1)"
[ -d "${SRC}/spotify_dock" ] || fail "Downloaded archive looks wrong."

# ---- 2. Swap into place (atomic-ish: new dir, then flip) ----
NEW="${DEST}/current.new"
rm -rf "${NEW}"
mkdir -p "${NEW}"
cp -r "${SRC}/spotify_dock" "${SRC}/extension" "${NEW}/"
mv "${DEST}/current" "${DEST}/current.old" 2>/dev/null || true
mv "${NEW}" "${DEST}/current"
rm -rf "${DEST}/current.old" "${TMP}"
ok "Installed to ${DEST}/current"

# ---- 3. CLI shim ----
mkdir -p "${BIN}"
cat > "${SHIM}" <<'PY'
#!/usr/bin/env python3
import os, sys
sys.path.insert(0, os.path.expanduser("~/.local/share/spotify-dock/current"))
from spotify_dock.cli import main
if __name__ == "__main__":
    sys.exit(main())
PY
chmod +x "${SHIM}"
ok "Command installed: ${SHIM}"

# ---- 4. GNOME Shell extension ----
rm -rf "${EXT_DIR}"
mkdir -p "${EXT_DIR}"
cp -r "${DEST}/current/extension/." "${EXT_DIR}/"
ok "Extension installed: ${EXT_UUID}"

echo -e "\n${BOLD}2/4${NC} Done. ${BOLD}3-4/4${NC} — running the setup wizard (auth + daemon):\n"
exec "${SHIM}" setup

#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/hermes-shared-browser"
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$config_dir" "$unit_dir" "$HOME/.hermes/browser-profiles"

if [[ ! -f "$config_dir/env" ]]; then
  chrome_bin=""
  for candidate in chromium-browser chromium google-chrome google-chrome-stable /snap/chromium/current/usr/lib/chromium-browser/chrome; do
    if command -v "$candidate" >/dev/null 2>&1 || [[ -x "$candidate" ]]; then
      chrome_bin="$candidate"
      break
    fi
  done
  chrome_bin="${chrome_bin:-chromium-browser}"

  novnc_web=""
  for candidate in /usr/share/novnc /usr/share/noVNC /opt/novnc; do
    if [[ -d "$candidate" ]]; then
      novnc_web="$candidate"
      break
    fi
  done
  novnc_web="${novnc_web:-/usr/share/novnc}"

  cat > "$config_dir/env" <<EOF
DISPLAY_NUM=99
SCREEN_GEOMETRY=1600x1000x24
CDP_HOST=127.0.0.1
CDP_PORT=9222
VNC_HOST=127.0.0.1
VNC_PORT=5900
NOVNC_HOST=127.0.0.1
NOVNC_PORT=6080
NOVNC_WEB_DIR=$novnc_web
CHROME_PROFILE_DIR=$HOME/.hermes/browser-profiles/shared
CHROME_BIN=$chrome_bin
EOF
  chmod 600 "$config_dir/env"
fi

cp "$repo_dir"/systemd/user/*.service "$unit_dir"/
systemctl --user daemon-reload

cat <<EOF
Installed user units to: $unit_dir
Config file: $config_dir/env

Next steps:
  1. Edit $config_dir/env and set NOVNC_HOST to your private/Tailscale IP if remote access is needed.
  2. Start services:
     systemctl --user enable --now hermes-browser-xvfb.service
     systemctl --user enable --now hermes-browser-chromium.service
     systemctl --user enable --now hermes-browser-vnc.service
     systemctl --user enable --now hermes-browser-novnc.service
  3. Run ./scripts/check-health.sh
  4. Set Hermes CDP URL:
     hermes config set browser.cdp_url http://127.0.0.1:9222
EOF

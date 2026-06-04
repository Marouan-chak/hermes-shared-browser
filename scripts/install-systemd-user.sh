#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
config_dir="${XDG_CONFIG_HOME:-$HOME/.config}/hermes-shared-browser"
unit_dir="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$config_dir" "$unit_dir" "$HOME/.hermes/browser-profiles"

if [[ -f /etc/debian_version ]]; then
  distro_note="Debian/Ubuntu detected. Run 'make install-deps' first if packages are missing."
else
  distro_note="Non-Debian distro detected. This repo is documented for Debian/Ubuntu for now; install equivalent packages manually."
fi

if [[ ! -f "$config_dir/env" ]]; then
  chrome_bin=""
  for candidate in chromium chromium-browser google-chrome google-chrome-stable /snap/chromium/current/usr/lib/chromium-browser/chrome; do
    if command -v "$candidate" >/dev/null 2>&1 || [[ -x "$candidate" ]]; then
      chrome_bin="$candidate"
      break
    fi
  done
  chrome_bin="${chrome_bin:-chromium}"

  novnc_web=""
  for candidate in /usr/share/novnc /usr/share/noVNC /opt/novnc; do
    if [[ -d "$candidate" ]]; then
      novnc_web="$candidate"
      break
    fi
  done
  novnc_web="${novnc_web:-/usr/share/novnc}"

  novnc_host="127.0.0.1"
  tailscale_hint=""
  if command -v tailscale >/dev/null 2>&1; then
    if ts_ip="$(tailscale ip -4 2>/dev/null | head -n 1)" && [[ -n "$ts_ip" ]]; then
      tailscale_hint="Detected Tailscale IPv4: $ts_ip. To expose noVNC on your Tailnet, set NOVNC_HOST=$ts_ip in $config_dir/env."
    fi
  fi

  cat > "$config_dir/env" <<EOF
DISPLAY_NUM=99
SCREEN_GEOMETRY=1600x1000x24
CDP_HOST=127.0.0.1
CDP_PORT=9222
VNC_HOST=127.0.0.1
VNC_PORT=5900
NOVNC_HOST=$novnc_host
NOVNC_PORT=6080
NOVNC_WEB_DIR=$novnc_web
CHROME_PROFILE_DIR=$HOME/.hermes/browser-profiles/shared
CHROME_BIN=$chrome_bin
# Optional: set with ./scripts/set-vnc-password.sh. Leave empty for no VNC password.
VNC_PASSWORD_FILE=
EOF
  chmod 600 "$config_dir/env"
else
  tailscale_hint="Existing config left unchanged: $config_dir/env"
fi

cp "$repo_dir"/systemd/user/*.service "$unit_dir"/
systemctl --user daemon-reload

cat <<EOF
Installed user units to: $unit_dir
Config file: $config_dir/env

$distro_note
${tailscale_hint:-}

Next steps:
  1. Review $config_dir/env. Keep CDP_HOST=127.0.0.1. Set NOVNC_HOST to a private/Tailscale IP only if remote access is needed.
  2. Optional but recommended when exposing noVNC beyond loopback:
     make set-vnc-password
  3. Start services:
     make start
  4. Run health checks:
     make health
  5. Set Hermes CDP URL:
     hermes config set browser.cdp_url http://127.0.0.1:9222
EOF

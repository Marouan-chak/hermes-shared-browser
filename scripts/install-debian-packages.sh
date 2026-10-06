#!/usr/bin/env bash
set -euo pipefail

if [[ ! -f /etc/debian_version ]]; then
  echo "This installer is intentionally Debian/Ubuntu focused for now." >&2
  echo "Install equivalent packages manually on other distributions." >&2
  exit 1
fi

if (( EUID == 0 )); then
  elevate=()
elif command -v sudo >/dev/null 2>&1; then
  elevate=(sudo)
else
  echo "sudo is required to install packages." >&2
  exit 1
fi

"${elevate[@]}" apt-get update

# Prefer common Debian/Ubuntu package names. chromium-browser exists on some
# Ubuntu releases, while Debian typically uses chromium.
packages=(xvfb xauth x11-utils x11vnc novnc websockify python3 iproute2 curl jq)
has_candidate() {
  local candidate
  candidate="$(apt-cache policy "$1" | awk '/Candidate:/ { print $2; exit }')"
  [[ -n "$candidate" && "$candidate" != '(none)' ]]
}
if has_candidate chromium; then
  packages=(chromium "${packages[@]}")
  if has_candidate chromium-sandbox; then
    packages=(chromium-sandbox "${packages[@]}")
  fi
elif has_candidate chromium-browser; then
  packages=(chromium-browser "${packages[@]}")
else
  echo "Could not find chromium or chromium-browser in apt metadata." >&2
  echo "Install Chromium manually, then set CHROME_BIN in ~/.config/hermes-shared-browser/env." >&2
  exit 1
fi

"${elevate[@]}" apt-get install -y "${packages[@]}"

echo "ok: Debian/Ubuntu dependencies installed"

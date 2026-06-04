#!/usr/bin/env bash
set -euo pipefail

if [[ ! -f /etc/debian_version ]]; then
  echo "This installer is intentionally Debian/Ubuntu focused for now." >&2
  echo "Install equivalent packages manually on other distributions." >&2
  exit 1
fi

if ! command -v sudo >/dev/null 2>&1; then
  echo "sudo is required to install packages." >&2
  exit 1
fi

sudo apt-get update

# Prefer common Debian/Ubuntu package names. chromium-browser exists on some
# Ubuntu releases, while Debian typically uses chromium.
packages=(xvfb x11vnc novnc websockify curl jq)
if apt-cache show chromium >/dev/null 2>&1; then
  packages=(chromium "${packages[@]}")
elif apt-cache show chromium-browser >/dev/null 2>&1; then
  packages=(chromium-browser "${packages[@]}")
else
  echo "Could not find chromium or chromium-browser in apt metadata." >&2
  echo "Install Chromium manually, then set CHROME_BIN in ~/.config/hermes-shared-browser/env." >&2
  packages=("${packages[@]}")
fi

sudo apt-get install -y "${packages[@]}"

echo "ok: Debian/Ubuntu dependencies installed"

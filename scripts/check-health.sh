#!/usr/bin/env bash
set -euo pipefail

config_file="${XDG_CONFIG_HOME:-$HOME/.config}/hermes-shared-browser/env"
services=(
  hermes-browser-xvfb.service
  hermes-browser-chromium.service
  hermes-browser-vnc.service
  hermes-browser-novnc.service
)

if [[ ! -f "$config_file" ]]; then
  echo "fail: missing config file: $config_file" >&2
  echo "Run: make install" >&2
  exit 1
fi

# shellcheck disable=SC1090
source "$config_file"

failures=0
warn() { echo "warn: $*" >&2; }
fail() { echo "fail: $*" >&2; failures=$((failures + 1)); }

for svc in "${services[@]}"; do
  if systemctl --user is-active --quiet "$svc"; then
    echo "ok: $svc active"
  else
    fail "$svc not active"
    systemctl --user --no-pager --lines=20 status "$svc" || true
  fi
done

echo
echo "listeners:"
ss -ltnp | grep -E ":(${CDP_PORT:-9222}|${VNC_PORT:-5900}|${NOVNC_PORT:-6080})\b" || warn "no matching listeners found"

echo
echo "cdp version:"
if ! curl -fsS "http://127.0.0.1:${CDP_PORT:-9222}/json/version" | { command -v jq >/dev/null && jq . || python3 -m json.tool; }; then
  fail "CDP did not respond on 127.0.0.1:${CDP_PORT:-9222}"
fi

echo
echo "security checks:"
if ss -ltnp | grep -E ":${CDP_PORT:-9222}\b" | grep -vqE "127\.0\.0\.1:${CDP_PORT:-9222}|\[::1\]:${CDP_PORT:-9222}"; then
  fail "CDP appears to be listening on a non-loopback address"
else
  echo "ok: CDP is loopback-only"
fi

if ss -ltnp | grep -E ":${VNC_PORT:-5900}\b" | grep -vqE "127\.0\.0\.1:${VNC_PORT:-5900}|\[::1\]:${VNC_PORT:-5900}"; then
  warn "VNC appears reachable beyond loopback; prefer exposing only noVNC, not raw VNC"
else
  echo "ok: raw VNC is loopback-only"
fi

if [[ "${NOVNC_HOST:-127.0.0.1}" != "127.0.0.1" && "${NOVNC_HOST:-}" != "localhost" ]]; then
  if [[ -z "${VNC_PASSWORD_FILE:-}" || ! -f "${VNC_PASSWORD_FILE:-/nonexistent}" ]]; then
    warn "noVNC is bound to ${NOVNC_HOST}:${NOVNC_PORT:-6080} but no VNC password file is configured"
    warn "Run: make set-vnc-password"
  else
    echo "ok: VNC password file configured for remote noVNC exposure"
  fi
else
  echo "ok: noVNC is loopback-only"
fi

if command -v hermes >/dev/null 2>&1; then
  configured_cdp="$(hermes config get browser.cdp_url 2>/dev/null || true)"
  if [[ "$configured_cdp" == "http://127.0.0.1:${CDP_PORT:-9222}" ]]; then
    echo "ok: Hermes browser.cdp_url points at local CDP"
  else
    warn "Hermes browser.cdp_url is not set to http://127.0.0.1:${CDP_PORT:-9222}"
    warn "Current value: ${configured_cdp:-<unset or unavailable>}"
  fi
else
  warn "hermes CLI not found in PATH; skipping browser.cdp_url check"
fi

if (( failures > 0 )); then
  echo "fail: $failures health check(s) failed" >&2
  exit 1
fi

echo "ok: health checks passed"

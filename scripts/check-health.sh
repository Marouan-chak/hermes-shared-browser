#!/usr/bin/env bash
set -euo pipefail

services=(
  hermes-browser-xvfb.service
  hermes-browser-chromium.service
  hermes-browser-vnc.service
  hermes-browser-novnc.service
)

for svc in "${services[@]}"; do
  if systemctl --user is-active --quiet "$svc"; then
    echo "ok: $svc active"
  else
    echo "fail: $svc not active" >&2
    systemctl --user --no-pager --lines=20 status "$svc" || true
    exit 1
  fi
done

echo
echo "listeners:"
ss -ltnp | grep -E ':(9222|5900|6080)\b' || true

echo
echo "cdp version:"
curl -fsS "http://127.0.0.1:9222/json/version" | { command -v jq >/dev/null && jq . || python3 -m json.tool; }

echo
echo "security check: CDP should be loopback-only"
if ss -ltnp | grep -E ':9222\b' | grep -vqE '127\.0\.0\.1:9222|\[::1\]:9222'; then
  echo "fail: CDP appears to be listening on a non-loopback address" >&2
  exit 1
fi

echo "ok: health checks passed"

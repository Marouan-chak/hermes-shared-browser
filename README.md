# Hermes Shared Browser

A small, reusable setup for running a persistent visible Chromium session on a headless Linux server, VPS, or homelab box so Hermes Agent can automate the same browser session that a human logs into.

This solves a common problem with remote agents: authentication-heavy websites need a real human login once, but the agent still needs browser automation afterward. The pattern is:

- Chromium runs headed under a virtual X display (`Xvfb`).
- The human connects through VNC/noVNC to log in, solve MFA, or inspect pages.
- Hermes connects locally to Chrome DevTools Protocol (CDP) and reuses the same persistent profile.
- CDP stays bound to `127.0.0.1` only. Never expose CDP to the network.

## Architecture

```text
Hermes Agent ── local CDP ──> 127.0.0.1:9222
                                │
                            Chromium
                                │
                           Xvfb :99
                                │
                  x11vnc 127.0.0.1:5900
                                │
             noVNC/websockify private-ip:6080
                                │
                     Human browser/VNC client
```

## Why not just expose CDP?

CDP is effectively remote code execution inside your authenticated browser profile. Anyone who can reach it can read cookies, navigate as you, execute JavaScript, download files, and control accounts. Keep it loopback-only.

Expose only pixels/keyboard through VNC/noVNC, and only on a trusted private path such as Tailscale, WireGuard, SSH tunnel, or a private LAN.

## Requirements

Tested on Linux with systemd user services.

Packages usually needed:

```bash
sudo apt-get update
sudo apt-get install -y chromium-browser xvfb x11vnc novnc websockify curl jq
```

Package names vary by distro:

- Debian/Ubuntu may use `chromium`, `chromium-browser`, or a Snap wrapper.
- Fedora: `chromium xorg-x11-server-Xvfb x11vnc python3-websockify novnc`.
- Arch: `chromium xorg-server-xvfb x11vnc websockify novnc`.

## Quick start

Clone this repo, then:

```bash
./scripts/install-systemd-user.sh
systemctl --user daemon-reload
systemctl --user enable --now hermes-browser-xvfb.service
systemctl --user enable --now hermes-browser-chromium.service
systemctl --user enable --now hermes-browser-vnc.service
systemctl --user enable --now hermes-browser-novnc.service
./scripts/check-health.sh
```

Set Hermes to use the local CDP endpoint:

```bash
hermes config set browser.cdp_url http://127.0.0.1:9222
```

Open noVNC from a machine that can reach your server:

```text
http://<server-private-ip>:6080/vnc.html
```

Log into sites manually in that browser. Hermes browser tools will then use the same authenticated Chromium profile.

## Configuration

The generated services read `~/.config/hermes-shared-browser/env`.

Defaults:

```bash
DISPLAY_NUM=99
SCREEN_GEOMETRY=1600x1000x24
CDP_HOST=127.0.0.1
CDP_PORT=9222
VNC_HOST=127.0.0.1
VNC_PORT=5900
NOVNC_HOST=127.0.0.1
NOVNC_PORT=6080
CHROME_PROFILE_DIR=$HOME/.hermes/browser-profiles/shared
CHROME_BIN=chromium-browser
```

For remote human access, set `NOVNC_HOST` to a private interface IP, for example your Tailscale IP:

```bash
mkdir -p ~/.config/hermes-shared-browser
$EDITOR ~/.config/hermes-shared-browser/env
```

Example:

```bash
NOVNC_HOST=100.x.y.z
```

Then restart noVNC:

```bash
systemctl --user restart hermes-browser-novnc.service
```

Do not change `CDP_HOST=127.0.0.1` unless you fully understand the security impact.

## Verification

```bash
systemctl --user status hermes-browser-xvfb.service --no-pager
systemctl --user status hermes-browser-chromium.service --no-pager
systemctl --user status hermes-browser-vnc.service --no-pager
systemctl --user status hermes-browser-novnc.service --no-pager

ss -ltnp | grep -E ':(9222|5900|6080)\b'
curl -fsS http://127.0.0.1:9222/json/version | jq .
curl -fsSI http://127.0.0.1:6080/ | head
```

Expected:

- CDP listens on `127.0.0.1:9222`.
- VNC listens on `127.0.0.1:5900`.
- noVNC listens on your configured private interface/port.
- `/json/version` returns a Chromium version and a `webSocketDebuggerUrl`.

## Hermes Agent usage

After configuring `browser.cdp_url`, Hermes browser tools use the shared browser. You can also point any CDP-capable automation at:

```text
http://127.0.0.1:9222
```

A useful workflow:

1. Open noVNC.
2. Log into the target website manually.
3. Ask Hermes to continue in that browser session.
4. Keep CDP local and use noVNC only for human interaction.

## Security checklist

- [ ] CDP bound to `127.0.0.1` only.
- [ ] VNC bound to `127.0.0.1` only, unless additionally protected.
- [ ] noVNC exposed only on VPN/Tailnet/private LAN or behind auth.
- [ ] Browser profile directory is not world-readable.
- [ ] Do not commit cookies, profiles, screenshots, or logs containing secrets.
- [ ] Restart Chromium only when nobody is mid-login.

## Troubleshooting

### noVNC opens but screen is blank

Check Xvfb and Chromium:

```bash
journalctl --user -u hermes-browser-xvfb.service -n 100 --no-pager
journalctl --user -u hermes-browser-chromium.service -n 100 --no-pager
```

### CDP does not respond

```bash
curl -v http://127.0.0.1:9222/json/version
journalctl --user -u hermes-browser-chromium.service -n 100 --no-pager
```

### Chromium exits immediately

Set `CHROME_BIN` to the real binary path in `~/.config/hermes-shared-browser/env`. Some Snap/wrapper binaries return before the browser process is ready under systemd.

### GPU/VAAPI warnings

They are usually harmless in virtual-display setups. The sample service disables GPU acceleration.

## License

MIT.

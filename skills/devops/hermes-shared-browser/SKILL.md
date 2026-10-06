---
name: hermes-shared-browser
description: Configure a persistent visible Chromium session for Hermes Agent on a headless Linux server, with loopback-only CDP, authenticated VNC/noVNC, private-network access, health checks, and troubleshooting.
version: 1.1.0
author: Hermes Agent
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [hermes, browser, cdp, chromium, xvfb, vnc, novnc, tailscale, devops]
    related_skills: [hermes-agent]
---

# Hermes Shared Browser

## Scope

Use this skill to set up or troubleshoot a browser that a human and Hermes can share on a Linux server. Hermes supplies browser automation through `browser.cdp_url` and `/browser connect`; this project supplies the visible runtime. Use the `hermes-agent` skill for general Hermes installation or provider configuration.

Reference repository: https://github.com/Marouan-chak/hermes-shared-browser

```text
Hermes -> CDP 127.0.0.1:9222 -> Chromium -> Xvfb
                                            |
                          VNC 127.0.0.1:5900 -> noVNC
                                            |
                               Human via SSH/private VPN
```

CDP and VNC both grant access to authenticated accounts. Keep CDP and raw VNC local. Expose noVNC only over an encrypted private route, with a VNC password for any non-loopback bind. Do not commit profiles, cookies, passwords, local config, browsing captures, or private logs.

## Installation

The package installer targets Debian/Ubuntu with apt. Python 3.9 or newer and systemd user services are required. The Debian 12 stack is covered by a disposable integration test. Ubuntu Snap Chromium can need additional profile/Xauthority configuration; consult the README's troubleshooting notes.

Run browser services under the user's ordinary account, never as root. Root is needed only for OS packages:

```bash
git clone https://github.com/Marouan-chak/hermes-shared-browser.git
cd hermes-shared-browser
make install-deps
make install
make start
make health
```

Install copies a runtime helper into the user's config directory and renders systemd unit templates. Moving the checkout does not break installed services. Run `make install` again after repository updates; it preserves existing settings. Do not copy the source unit templates directly into systemd.

## Configuration

Default: `~/.config/hermes-shared-browser/env`. A configured `XDG_CONFIG_HOME` is honored by the installer and commands; generated units retain that absolute path.

Config uses `KEY=VALUE` data, not executable shell syntax. Quote paths containing spaces. Only leading `$HOME/`, `${HOME}/`, and `~/` in paths are expanded. Do not use commands, `export`, or unknown keys. The runtime rejects unsafe addresses, duplicate ports, malformed geometry, and non-private config/password files.

Common settings:

```bash
DISPLAY_NUM=99
SCREEN_GEOMETRY=1600x1000x24
CDP_HOST=127.0.0.1
CDP_PORT=9222
VNC_HOST=127.0.0.1
VNC_PORT=5900
NOVNC_HOST=127.0.0.1
NOVNC_PORT=6080
NOVNC_WEB_DIR=/usr/share/novnc
CHROME_PROFILE_DIR=$HOME/.hermes/browser-profiles/shared
CHROME_BIN=chromium
WEBSOCKIFY_BIN=websockify
VNC_PASSWORD_FILE=
```

CDP/VNC must remain `127.0.0.1`. noVNC accepts literal loopback, RFC1918, Tailscale (`100.64.0.0/10`), or IPv6 ULA addresses; never wildcard/public addresses. Ports are distinct and between 1024 and 65535. Use a dedicated browser profile, separate from desktop Chromium.

## Human access and Hermes

Keep the loopback defaults for SSH access. On the laptop:

```bash
ssh -N -L 6080:127.0.0.1:6080 user@server
```

Open `http://127.0.0.1:6080/vnc.html` on the laptop. To bind directly to a private VPN address instead, first set the VNC password:

```bash
make set-vnc-password
```

Then edit the config:

```bash
NOVNC_HOST=<private-or-tailnet-ip>
NOVNC_PORT=6080
```

Restart VNC before noVNC so the password is active:

```bash
systemctl --user restart hermes-browser-vnc.service hermes-browser-novnc.service
make health
```

Open `http://<private-or-tailnet-ip>:6080/vnc.html` from an allowed VPN device. Restrict access with VPN ACLs. Private LAN addresses alone do not encrypt HTTP or VNC; use an encrypted VPN, SSH, or authenticated HTTPS proxy.

A configured password file that disappears causes startup to fail. The runtime never falls back to passwordless access. noVNC also checks the already-running VNC server's authentication, rather than trusting that a saved password has taken effect.

On the Hermes server:

```bash
hermes config set browser.cdp_url http://127.0.0.1:9222
```

Use the configured CDP port if changed. Relaunch an existing Hermes session after a configuration change. The human can log in and complete MFA through noVNC, then Hermes can continue using that same profile.

## Verification and troubleshooting

```bash
make status
make health
```

Health checks verify all services, exact bind addresses, CDP version/websocket URL, the noVNC HTML page, live VNC authentication, and profile permissions. They return failure for missing listeners or unsafe authentication. The noVNC HTTP check uses its configured address, including a private VPN bind.

Inspect failures:

```bash
journalctl --user -u hermes-browser-xvfb.service -n 100 --no-pager
journalctl --user -u hermes-browser-chromium.service -n 100 --no-pager
journalctl --user -u hermes-browser-vnc.service -n 100 --no-pager
journalctl --user -u hermes-browser-novnc.service -n 100 --no-pager
```

A blank screen can mean a bad Chromium executable, occupied profile, or failed Xvfb. The launcher sets the actual `DISPLAY`, waits for Xvfb, and uses a private Xauthority cookie. Chromium's sandbox stays enabled. Never recommend disabling it as a production workaround.

Use absolute binary paths if needed. `WEBSOCKIFY_BIN` is supported. Snap Chromium may need a profile inside `~/snap/chromium/common/` and can restrict custom Xauthority paths; a native package is preferable when confinement prevents access.

After fixing a repeated startup failure:

```bash
systemctl --user reset-failed hermes-browser-xvfb.service hermes-browser-chromium.service hermes-browser-vnc.service hermes-browser-novnc.service
make restart
make health
```

`make stop` stops the stack but retains startup at login. `make disable` also disables startup. Systemd user lingering is an optional administrator choice for operation after logout/at boot.

## Contributions and reporting

Run `make validate` and `make test`. With runtime dependencies installed, `make test-integration` uses only disposable state and verifies the real CDP/VNC/noVNC stack and browser persistence. Do not claim a production setup is active based only on these repository tests: report actual service, listener, and human/Hermes-session evidence separately.

Before a public commit, inspect staged names and content and scan with a redacting secret scanner. CI scans history and the working tree with Gitleaks. Keep documentation generic: use placeholders, never real private IPs, internal hostnames, account IDs, tokens, customer data, or personal paths. Do not paste raw config or authenticated browser output into public logs or issues.

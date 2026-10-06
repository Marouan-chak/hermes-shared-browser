# Hermes Shared Browser

A small deployment wrapper for Hermes Agent's existing Chromium CDP support. It gives a headless Linux server a persistent browser that a human can see, log into, and share with Hermes.

Hermes supplies the browser automation engine through `browser.cdp_url` and `/browser connect`. This repository supplies the visible browser runtime: systemd user services, Xvfb, x11vnc, and noVNC. The runtime helper uses Python's standard library; no pip dependencies are needed.

## Architecture

```text
Hermes Agent -> CDP 127.0.0.1:9222 -> Chromium -> Xvfb :99
                                                |
                              x11vnc 127.0.0.1:5900
                                                |
                           noVNC 127.0.0.1:6080
                                                |
                    Human browser via SSH or private VPN
```

CDP controls authenticated browser sessions. Keep it local. VNC/noVNC also grants interactive access to those accounts, so use an encrypted private connection.

## Requirements

A Debian/Ubuntu-style system with apt, systemd user services, and Python 3.9 or newer. The Debian 12 browser stack is covered by the integration test. Ubuntu Chromium packaging varies; see the Snap notes below. Other distributions can install equivalent tools manually.

Run the services as your normal user. Only OS package installation needs root:

```bash
make install-deps
make install
make start
make health
```

`make install-deps` installs Chromium, Xvfb, xauth, xdpyinfo, x11vnc, noVNC, websockify, Python, iproute2, curl, and jq. It works with sudo or directly as root. `make install` copies the runtime into your config directory, so moving the checkout afterward does not break the services. Reinstall after updating this repository to update that installed copy.

Configure Hermes on the same server:

```bash
hermes config set browser.cdp_url http://127.0.0.1:9222
```

Relaunch an existing Hermes session after changing its configuration.

## Connect from your laptop

All three network services use loopback by default. From your laptop, forward noVNC over SSH:

```bash
ssh -N -L 6080:127.0.0.1:6080 user@server
```

Then open [noVNC](http://127.0.0.1:6080/vnc.html) on the laptop. Log into sites and complete MFA there; Hermes can then use the same authenticated Chromium profile.

For direct access through Tailscale or another private VPN, follow [the Tailscale guide](docs/tailscale.md). A VNC password is required before binding noVNC beyond loopback. Never expose CDP or raw VNC to the network.

## Configuration

The default config is `~/.config/hermes-shared-browser/env`. If `XDG_CONFIG_HOME` is set, installation and local commands use `$XDG_CONFIG_HOME/hermes-shared-browser/env`. The generated units keep that exact absolute path, independent of the systemd manager's environment.

The file contains `KEY=VALUE` data, not executable shell code. Single or double quotes support spaces; full-line and trailing comments are accepted. `$HOME/`, `${HOME}/`, and `~/` are expanded only at the start of path values. Other shell substitutions are never executed. Unknown keys and invalid settings fail with an error.

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
NOVNC_WEB_DIR=/usr/share/novnc
CHROME_PROFILE_DIR=$HOME/.hermes/browser-profiles/shared
CHROME_BIN=chromium
WEBSOCKIFY_BIN=websockify
VNC_PASSWORD_FILE=
```

Installation detects a Chromium executable and noVNC web directory when available. `CHROME_BIN` and `WEBSOCKIFY_BIN` can also be absolute executable paths. Use a dedicated Chromium profile, separate from your desktop browser.

CDP and VNC bindings are enforced as `127.0.0.1`. noVNC accepts literal loopback, RFC1918, Tailscale (`100.64.0.0/10`), and IPv6 ULA addresses. Wildcard/public addresses and hostnames are rejected. Ports must be distinct and between 1024 and 65535.

Edit the config and restart the stack:

```bash
$EDITOR ~/.config/hermes-shared-browser/env
make restart
make health
```

Keep the config and VNC password private (mode `600`). The installer and launcher set the profile directory to `700`. The virtual X display requires a private Xauthority cookie and does not accept TCP connections. Chromium retains its sandbox; the launcher does not force plaintext password storage.

## Service lifecycle

```bash
make status       # Show all four service states
make health       # Check services, listeners, CDP, VNC auth, noVNC, and profile permissions
make stop         # Stop the stack; it can still start at the next login
make start        # Enable startup at login and start the stack
make restart      # Restart the whole stack; interrupts browser work
make disable      # Stop the stack and disable startup at login
```

Services start after login. To keep them running after logout or start them at boot, an administrator can enable user lingering:

```bash
sudo loginctl enable-linger "$USER"
```

Reinstalling preserves existing config. To upgrade from individually enabled services:

```bash
make stop
make install
make start
make health
```

The source unit files are templates. Install them with `make install`; copying them directly into systemd does not render the runtime/config paths.

## Hermes skill

The reusable skill is [skills/devops/hermes-shared-browser/SKILL.md](skills/devops/hermes-shared-browser/SKILL.md). Copy its directory into your Hermes skills directory and start a new Hermes session. See [Hermes integration](docs/hermes-agent.md) for the workflow.

## Troubleshooting

Inspect the component that fails:

```bash
journalctl --user -u hermes-browser-chromium.service -n 100 --no-pager
journalctl --user -u hermes-browser-xvfb.service -n 100 --no-pager
journalctl --user -u hermes-browser-vnc.service -n 100 --no-pager
journalctl --user -u hermes-browser-novnc.service -n 100 --no-pager
```

A missing password file is an error, even on loopback. Recreate it with `make set-vnc-password`, then restart VNC and noVNC. The noVNC launcher verifies the running VNC server's authentication before forwarding it, so saving a password without restarting VNC is insufficient.

If Chromium exits, check `CHROME_BIN`, profile ownership, and whether another Chromium process already uses that profile. Display-dependent services wait for Xvfb to become ready rather than racing its startup. GPU/VAAPI warnings can be harmless on a virtual display.

Ubuntu's `chromium-browser` can be a Snap wrapper. New installs choose `~/snap/chromium/common/hermes-shared-browser` for a detected Snap/wrapper. Existing installs may need that profile path configured manually. Snap confinement can also restrict access to a custom Xauthority path; prefer a native Chromium package if its logs report denied access. Do not work around sandbox failures by disabling Chromium's sandbox.

If systemd reports start limits after a configuration failure, fix the setting, then run:

```bash
systemctl --user reset-failed hermes-browser-xvfb.service hermes-browser-chromium.service hermes-browser-vnc.service hermes-browser-novnc.service
make restart
```

## Development

Validation needs Bash, ShellCheck, Python, Git, and `systemd-analyze`. Regression tests need only Python:

```bash
make validate
make test
```

With the runtime dependencies installed, run `make test-integration` as a normal user. It uses a temporary profile, config, display, and ports; verifies CDP, authenticated VNC, the noVNC websocket bridge, listener exposure, X authorization, and browser-state persistence; then removes its processes and files. CI runs this in Debian, plus regression tests on Python 3.9, 3.11, and 3.14. Container CI uses a test-only sandbox override for its disposable profile because container kernels can prohibit Chromium's sandbox namespaces. Production launchers do not use that override.

CI also scans Git history and the working tree with a checksum-pinned Gitleaks binary. Never commit local config, cookies, profiles, passwords, browsing captures, or private logs. See [security notes](docs/security.md).

## License

MIT.

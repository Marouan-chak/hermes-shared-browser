# Tailscale access

Expose noVNC only to permitted devices in your Tailnet. CDP and raw VNC remain local.

1. Install and start the stack using the README, then save a VNC password:

```bash
make set-vnc-password
```

2. Find the server's Tailscale IPv4:

```bash
tailscale ip -4
```

3. Edit `~/.config/hermes-shared-browser/env` (or the corresponding `XDG_CONFIG_HOME` path). Replace the placeholder with the server's actual Tailnet IP:

```bash
NOVNC_HOST=<tailscale-ip>
NOVNC_PORT=6080
CDP_HOST=127.0.0.1
VNC_HOST=127.0.0.1
```

4. Restart VNC before noVNC so the password is active, then verify:

```bash
systemctl --user restart hermes-browser-vnc.service hermes-browser-novnc.service
make health
```

5. Open `http://<tailscale-ip>:6080/vnc.html` from an allowed Tailnet device. Restrict port 6080 to the appropriate users/devices with Tailnet ACLs. The HTTP traffic travels inside the encrypted VPN; do not expose it through a public port or tunnel.

Health checks contact the configured noVNC address. After binding to a Tailnet IP, checking `127.0.0.1:6080` is no longer the right test. A missing Tailnet interface makes noVNC startup fail rather than binding elsewhere.

For an SSH-only setup, retain the default loopback binding and use the SSH forwarding instructions in the README.

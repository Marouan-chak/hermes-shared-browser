# Tailscale example

This project works well with Tailscale because noVNC can be exposed only to devices in your Tailnet while CDP remains local.

1. Find the server's Tailscale IP:

```bash
tailscale ip -4
```

2. Edit the env file:

```bash
$EDITOR ~/.config/hermes-shared-browser/env
```

Set:

```bash
NOVNC_HOST=<tailscale-ip>
NOVNC_PORT=6080
CDP_HOST=127.0.0.1
VNC_HOST=127.0.0.1
```

3. Restart noVNC:

```bash
systemctl --user restart hermes-browser-novnc.service
```

4. Open from your laptop:

```text
http://<tailscale-ip>:6080/vnc.html
```

Do not set `CDP_HOST` to the Tailscale IP.

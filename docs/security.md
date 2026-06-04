# Security notes

The important boundary is CDP vs pixels.

## CDP

Chrome DevTools Protocol can fully control the browser and read authenticated state. Treat it like a privileged local API.

Recommended:

- Bind CDP to `127.0.0.1` only.
- Do not publish CDP through Caddy, nginx, Cloudflare Tunnel, Tailscale Serve, LAN listeners, or public ports.
- If a remote automation process must use CDP, connect through SSH port forwarding and restrict access tightly.

## VNC/noVNC

VNC/noVNC exposes pixels, keyboard, and mouse. It is still sensitive, but it is the appropriate interface for human login/inspection.

Recommended:

- Keep raw VNC loopback-only.
- Expose noVNC only through a VPN/Tailnet/private LAN or behind strong auth.
- Prefer a private bind address over `0.0.0.0`.

## Browser profile

The browser profile contains cookies, local storage, OAuth state, downloaded files, and browsing history.

Recommended:

- Keep it under your user account.
- Do not commit or back it up into public repos.
- Do not run untrusted websites and privileged admin sessions in the same profile unless you accept that risk.

# Security notes

CDP and VNC/noVNC both grant access to authenticated accounts. Use this stack under a trusted local user account on a machine you control.

## Enforced boundaries

- CDP and raw VNC bind to `127.0.0.1` only. Both x11vnc's IPv6 support and LibVNCServer's separate IPv6 port are disabled.
- noVNC accepts loopback or explicit private/VPN addresses. Wildcard and public binds are refused.
- Remote noVNC requires a readable, user-owned VNC password file with private permissions. Missing or invalid configured files cause startup to fail; authentication never silently falls back to passwordless mode.
- noVNC checks the running VNC server's advertised authentication before forwarding it. `make health` checks it again, along with exact listener addresses and the CDP websocket URL.
- Config is parsed as data, without shell evaluation. Private config and password files use mode `600`; the profile and config directories use `700`.
- Xvfb uses a private Xauthority cookie and disables TCP. Chromium keeps its sandbox, and no plaintext password-store flag is forced.

## Network transport

Prefer SSH forwarding or an encrypted VPN such as Tailscale/WireGuard. The built-in noVNC web server uses HTTP and VNC authentication does not encrypt the session. A private LAN address alone provides no transport encryption. Use a VPN or an authenticated HTTPS proxy rather than sending account interactions across an untrusted LAN.

Traditional VNC passwords use only the first eight characters and are stored in a reversible format. They add an access check; they do not replace the VPN/SSH boundary. Restrict which devices can reach noVNC with your VPN ACLs. Stop the stack when access is no longer needed.

Do not publish CDP through nginx, Caddy, Cloudflare Tunnel, Tailscale Serve, or public ports. Remote automation should use tightly restricted SSH forwarding. Loopback cannot protect CDP against untrusted processes running on the same host, especially under the same user.

## Browser state and publication

The profile contains cookies, storage, history, and potentially saved credentials. Keep it out of public repositories and backups intended for sharing. Separate unrelated privileged sessions into different profiles. Files downloaded through Chromium may be stored outside the profile, for example in your Downloads directory; protect those too.

`.gitignore` excludes common local state, credentials, browsing captures, and logs. CI runs Gitleaks over history and the working tree. These controls do not identify every kind of personal data: inspect staged filenames and content before publishing, and never use `git add -f` for local browser state.

To report a vulnerability, use the repository's private GitHub security reporting feature if available. Do not post tokens, cookies, passwords, or sensitive account evidence in public issues.

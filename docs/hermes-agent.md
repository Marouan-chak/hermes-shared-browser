# Hermes Agent integration

Hermes Agent can use a local CDP endpoint for browser automation.

After this stack is running:

```bash
hermes config set browser.cdp_url http://127.0.0.1:9222
```

Then use Hermes browser tools normally. The agent connects to the visible Chromium profile instead of creating an ephemeral browser session.

Recommended workflow:

1. Open noVNC.
2. Log into the account manually.
3. Ask Hermes to continue the task using the browser.
4. Keep CDP bound to loopback.

For remote/headless servers, this lets a MacBook/laptop user handle login/MFA visually while the Hermes process running on the server uses the same authenticated session.

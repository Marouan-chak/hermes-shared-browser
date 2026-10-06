"""Real Xvfb/Chromium/VNC/noVNC smoke test using only disposable local state."""

import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
import os
from pathlib import Path
import shlex
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import ProxyHandler, Request, build_opener


REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("browser_runtime", REPO / "scripts/browser_runtime.py")
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)
HTTP = build_opener(ProxyHandler({}))


def wait_for(operation, timeout=30):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        try:
            return operation()
        except (OSError, ValueError, AssertionError) as exc:
            last = exc
            time.sleep(0.2)
    raise RuntimeError(f"readiness check timed out: {last}")


def available_ports():
    reservations = []
    try:
        for _ in range(3):
            connection = socket.socket()
            connection.bind(("127.0.0.1", 0))
            reservations.append(connection)
        return [str(connection.getsockname()[1]) for connection in reservations]
    finally:
        for connection in reservations:
            connection.close()


def websocket_bridge(port):
    """Prove the HTTP websocket endpoint actually forwards an RFB server banner."""
    key = base64.b64encode(os.urandom(16)).decode()
    with socket.create_connection(("127.0.0.1", int(port)), timeout=5) as connection:
        request = (f"GET /websockify HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
                   "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                   f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        connection.sendall(request.encode())
        header = b""
        while not header.endswith(b"\r\n\r\n"):
            chunk = connection.recv(1)
            if not chunk or len(header) > 65536:
                raise RuntimeError("invalid websocket upgrade response")
            header += chunk
        assert header.startswith(b"HTTP/1.1 101"), header[:128]
        accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest())
        assert accept in header
        frame = b""
        while len(frame) < 14:
            chunk = connection.recv(14 - len(frame))
            if not chunk:
                raise RuntimeError("websocket bridge closed before VNC banner")
            frame += chunk
        assert frame[0] & 0x0f == 2 and frame[1] == 12, frame
        assert frame[2:] == b"RFB 003.008\n", frame


class FixturePage(BaseHTTPRequestHandler):
    def do_GET(self):
        write = "localStorage.setItem('shared-browser-fixture', 'persisted');" if self.path == "/write" else ""
        body = (f"<html><script>{write}document.title = localStorage.getItem('shared-browser-fixture') || 'empty';"
                "</script></html>").encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def smoke_test():
    if os.getuid() == 0:
        raise RuntimeError("run integration tests as a normal user so Chromium keeps its sandbox")
    for name in ("Xvfb", "xauth", "xdpyinfo", "x11vnc", "websockify", "chromium", "ss"):
        runtime.executable(name)
    processes = {}
    with tempfile.TemporaryDirectory(prefix="hermes-browser-smoke-") as temporary:
        root = Path(temporary)
        profile = root / "profile with spaces"
        config = root / "env"
        cdp, vnc, novnc = available_ports()
        display = next(str(number) for number in range(199, 999)
                       if not Path(f"/tmp/.X{number}-lock").exists()
                       and not Path(f"/tmp/.X11-unix/X{number}").exists())
        password = root / "vnc.pass"
        subprocess.run(["x11vnc", "-norc", "-storepasswd", str(password)], check=True,
                       input="testpass\ntestpass\ny\n", text=True, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        password.chmod(0o600)
        values = runtime.defaults()
        values.update(DISPLAY_NUM=display, CDP_PORT=cdp, VNC_PORT=vnc, NOVNC_PORT=novnc,
                      CHROME_PROFILE_DIR=str(profile), VNC_PASSWORD_FILE=str(password))
        # Some container kernels prohibit Chromium's sandbox namespaces. This test-only
        # opt-in touches a disposable profile and never changes the production launcher.
        if os.environ.get("HERMES_TEST_UNSANDBOXED") == "1":
            wrapper = root / "test-chromium"
            wrapper.write_text('#!/bin/sh\nexec /usr/bin/chromium --no-sandbox "$@"\n')
            wrapper.chmod(0o700)
            values["CHROME_BIN"] = str(wrapper)
            print("test-only: Chromium sandbox disabled for this disposable container profile")
        runtime.atomic_write(config, "".join(f"{key}={shlex.quote(value)}\n" for key, value in values.items()))
        environment = dict(os.environ, HERMES_BROWSER_CONFIG=str(config))
        fixture = ThreadingHTTPServer(("127.0.0.1", 0), FixturePage)
        baseline = runtime.listeners()
        thread = threading.Thread(target=fixture.serve_forever, daemon=True)
        thread.start()
        logs = []

        def start(name):
            log = (root / f"{name}.log").open("a")
            logs.append(log)
            process = subprocess.Popen([sys.executable, "-B", str(REPO / "scripts/browser_runtime.py"),
                                        "launch", name], env=environment, stdout=log, stderr=log,
                                       start_new_session=True)
            processes[name] = process

        def stop(name):
            process = processes.pop(name, None)
            if process:
                if name == "chromium" and process.poll() is None:
                    # Closing the browser's windows lets Chromium flush profile storage.
                    try:
                        targets = runtime.fetch_json(f"http://127.0.0.1:{cdp}/json/list")
                        for target in targets:
                            if target.get("type") == "page":
                                with HTTP.open(f"http://127.0.0.1:{cdp}/json/close/{target['id']}", timeout=5):
                                    pass
                        process.wait(timeout=10)
                    except (OSError, ValueError, subprocess.TimeoutExpired):
                        pass
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)

        def navigate(path):
            url = f"http://127.0.0.1:{fixture.server_port}{path}"
            with HTTP.open(Request(f"http://127.0.0.1:{cdp}/json/new?{url}", method="PUT"), timeout=5) as response:
                target = json.load(response)

            def loaded():
                targets = runtime.fetch_json(f"http://127.0.0.1:{cdp}/json/list")
                assert any(item["id"] == target["id"] and item["title"] == "persisted" for item in targets)

            wait_for(loaded)

        try:
            start("xvfb")
            start("chromium")
            start("vnc")
            start("novnc")
            wait_for(lambda: runtime.fetch_json(f"http://127.0.0.1:{cdp}/json/version"))
            wait_for(lambda: runtime.check_vnc_auth(values))
            wait_for(lambda: websocket_bridge(novnc))
            with HTTP.open(f"http://127.0.0.1:{novnc}/vnc.html", timeout=5) as response:
                assert response.status == 200 and b"<html" in response.read().lower()
            bound = runtime.listeners()
            assert set(bound) - set(baseline) == {cdp, vnc, novnc}, "unexpected additional TCP listener"
            for port in (cdp, vnc, novnc):
                assert bound[port] == {"127.0.0.1"}, (port, bound[port])
            assert profile.stat().st_mode & 0o777 == 0o700
            unauthorized = subprocess.run(["xdpyinfo", "-display", f":{display}"],
                env=dict(environment, XAUTHORITY=str(root / "missing-authority")),
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            assert unauthorized.returncode != 0, "Xvfb accepted a client without its cookie"
            navigate("/write")
            stop("chromium")
            start("chromium")
            wait_for(lambda: runtime.fetch_json(f"http://127.0.0.1:{cdp}/json/version"))
            navigate("/read")
            print("ok: real CDP, authenticated VNC, noVNC websocket bridge, loopback bindings, X auth,")
            print("    private profile, and browser state persistence across Chromium restart")
        except Exception:
            for name in processes:
                path = root / f"{name}.log"
                print(f"--- disposable {name} log ---\n{path.read_text()[-4000:]}", file=sys.stderr)
            raise
        finally:
            for name in ("novnc", "vnc", "chromium", "xvfb"):
                stop(name)
            fixture.shutdown()
            fixture.server_close()
            thread.join(timeout=5)
            for log in logs:
                log.close()


if __name__ == "__main__":
    smoke_test()

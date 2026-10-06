#!/usr/bin/env python3
"""Configuration, launchers, and checks for the shared browser (stdlib only)."""

import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener


SERVICES = tuple(f"hermes-browser-{name}.service" for name in
                 ("xvfb", "chromium", "vnc", "novnc"))
PRIVATE_NETWORKS = tuple(ipaddress.ip_network(value) for value in
                         ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16",
                          "100.64.0.0/10", "fc00::/7"))


class ConfigError(ValueError):
    pass


def config_path():
    root = Path(os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config"))
    path = Path(os.environ.get("HERMES_BROWSER_CONFIG") or str(root / "hermes-shared-browser/env"))
    if not root.is_absolute() or not path.is_absolute():
        raise ConfigError("XDG_CONFIG_HOME and HERMES_BROWSER_CONFIG must be absolute paths")
    return path


def defaults():
    return {
        "DISPLAY_NUM": "99",
        "SCREEN_GEOMETRY": "1600x1000x24",
        "CDP_HOST": "127.0.0.1",
        "CDP_PORT": "9222",
        "VNC_HOST": "127.0.0.1",
        "VNC_PORT": "5900",
        "NOVNC_HOST": "127.0.0.1",
        "NOVNC_PORT": "6080",
        "NOVNC_WEB_DIR": "/usr/share/novnc",
        "CHROME_PROFILE_DIR": str(Path.home() / ".hermes/browser-profiles/shared"),
        "CHROME_BIN": "chromium",
        "WEBSOCKIFY_BIN": "websockify",
        "VNC_PASSWORD_FILE": "",
    }


def private_file(path):
    info = path.stat()
    if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise ConfigError(f"{path} must be a regular file owned by you with mode 600")


def load_config(path=None):
    path = path or config_path()
    if not path.is_file():
        raise ConfigError(f"missing config: {path}; run make install")
    private_file(path)
    values = defaults()
    for number, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = re.fullmatch(r"([A-Z][A-Z0-9_]*)\s*=(.*)", line)
        if not match or match[1] not in values:
            raise ConfigError(f"invalid or unknown setting on config line {number}")
        try:
            parts = shlex.split(match[2], comments=True)
        except ValueError as exc:
            raise ConfigError(f"invalid quoting on config line {number}") from exc
        if len(parts) > 1:
            raise ConfigError(f"quote values containing spaces on config line {number}")
        value = parts[0] if parts else ""
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ConfigError(f"control character on config line {number}")
        values[match[1]] = value
    for key in ("CHROME_PROFILE_DIR", "NOVNC_WEB_DIR", "VNC_PASSWORD_FILE", "CHROME_BIN", "WEBSOCKIFY_BIN"):
        value = values[key]
        for prefix in ("$HOME/", "${HOME}/", "~/"):
            if value.startswith(prefix):
                value = str(Path.home() / value[len(prefix):])
                break
        values[key] = value
    validate_config(values)
    return values


def validate_config(values):
    for key in ("CDP_HOST", "VNC_HOST"):
        if values[key] == "localhost":
            values[key] = "127.0.0.1"
        if values[key] != "127.0.0.1":
            raise ConfigError(f"{key} must be 127.0.0.1")
    if values["NOVNC_HOST"] == "localhost":
        values["NOVNC_HOST"] = "127.0.0.1"
    try:
        address = ipaddress.ip_address(values["NOVNC_HOST"])
    except ValueError as exc:
        raise ConfigError("NOVNC_HOST must be a literal loopback or private IP address") from exc
    if not (address.is_loopback or any(address in network for network in PRIVATE_NETWORKS)):
        raise ConfigError("NOVNC_HOST must be loopback, RFC1918, Tailscale, or an IPv6 ULA address")
    values["NOVNC_HOST"] = str(address)
    for key in ("CDP_PORT", "VNC_PORT", "NOVNC_PORT"):
        if not re.fullmatch(r"[0-9]{1,5}", values[key]) or not 1024 <= int(values[key]) <= 65535:
            raise ConfigError(f"{key} must be an unprivileged port between 1024 and 65535")
        values[key] = str(int(values[key]))
    if len({values[key] for key in ("CDP_PORT", "VNC_PORT", "NOVNC_PORT")}) != 3:
        raise ConfigError("CDP_PORT, VNC_PORT, and NOVNC_PORT must be different")
    if not re.fullmatch(r"[0-9]{1,5}", values["DISPLAY_NUM"]):
        raise ConfigError("DISPLAY_NUM must be an integer between 0 and 65535")
    values["DISPLAY_NUM"] = str(int(values["DISPLAY_NUM"]))
    if int(values["DISPLAY_NUM"]) > 65535:
        raise ConfigError("DISPLAY_NUM must be an integer between 0 and 65535")
    if not re.fullmatch(r"[1-9][0-9]{0,4}x[1-9][0-9]{0,4}x(16|24|32)", values["SCREEN_GEOMETRY"]):
        raise ConfigError("SCREEN_GEOMETRY must be WIDTHxHEIGHTxDEPTH (depth 16, 24, or 32)")
    for key in ("CHROME_PROFILE_DIR", "NOVNC_WEB_DIR", "VNC_PASSWORD_FILE"):
        if values[key] and not Path(values[key]).is_absolute():
            raise ConfigError(f"{key} must be an absolute path")
        if key != "VNC_PASSWORD_FILE" and not values[key]:
            raise ConfigError(f"{key} must not be empty")
    for key in ("CHROME_BIN", "WEBSOCKIFY_BIN"):
        if not values[key] or values[key].startswith("-"):
            raise ConfigError(f"{key} must be an executable name or absolute path")


def password_path(values):
    if not values["VNC_PASSWORD_FILE"]:
        if not ipaddress.ip_address(values["NOVNC_HOST"]).is_loopback:
            raise ConfigError("remote noVNC requires a VNC password; run make set-vnc-password")
        return None
    path = Path(values["VNC_PASSWORD_FILE"])
    if not path.is_file():
        raise ConfigError("configured VNC password file is missing; refusing unauthenticated access")
    private_file(path)
    with path.open("rb") as stream:
        valid = len(stream.read(9)) == 8
    if not valid:
        raise ConfigError("invalid VNC password file; recreate it with make set-vnc-password")
    return path


def secure_directory(path):
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink() or path.stat().st_uid != os.getuid():
        raise ConfigError(f"{path} must be a directory owned by you, not a symlink")
    path.chmod(0o700)


def atomic_write(path, content, mode=0o600):
    """Replace in the same directory, preserving the old file on failure."""
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(content)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def executable(name):
    path = shutil.which(name)
    if not path:
        raise ConfigError(f"missing executable: {name}; install the runtime dependencies")
    return path


def wait_for_display(environment):
    probe = executable("xdpyinfo")
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        try:
            result = subprocess.run([probe, "-display", environment["DISPLAY"]], env=environment,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
            if result.returncode == 0:
                return
        except subprocess.TimeoutExpired:
            pass
        time.sleep(0.2)
    raise ConfigError("Xvfb display did not become ready within 15 seconds")


def launch(component):
    values = load_config()
    directory = config_path().parent
    os.umask(0o077)
    authority = directory / "xauthority"
    environment = dict(os.environ, DISPLAY=f":{values['DISPLAY_NUM']}", XAUTHORITY=str(authority))
    if component == "xvfb":
        xauth = executable("xauth")
        server = executable("Xvfb")
        secure_directory(directory)
        # A cookie protects the UNIX socket too; disabling TCP alone is insufficient.
        atomic_write(authority, "")
        subprocess.run([xauth, "-f", str(authority)], check=True,
                       input=f"add {environment['DISPLAY']} . {secrets.token_hex(16)}\n", text=True,
                       stdout=subprocess.DEVNULL)
        command = [server, environment["DISPLAY"], "-screen", "0", values["SCREEN_GEOMETRY"],
                   "-auth", str(authority), "-nolisten", "tcp"]
    elif component == "chromium":
        browser = executable(values["CHROME_BIN"])
        secure_directory(Path(values["CHROME_PROFILE_DIR"]))
        wait_for_display(environment)
        command = [browser, f"--user-data-dir={values['CHROME_PROFILE_DIR']}",
                   "--remote-debugging-address=127.0.0.1", f"--remote-debugging-port={values['CDP_PORT']}",
                   "--no-first-run", "--no-default-browser-check", "--disable-gpu",
                   "--disable-dev-shm-usage", "about:blank"]
    elif component == "vnc":
        server = executable("x11vnc")
        password = password_path(values)
        wait_for_display(environment)
        # Both x11vnc and LibVNCServer have IPv6 listeners; disable both explicitly.
        command = [server, "-norc", "-display", environment["DISPLAY"], "-auth", str(authority),
                   "-listen", "127.0.0.1", "-no6", "-noipv6", "-rfbportv6", "-1",
                   "-rfbport", values["VNC_PORT"],
                   "-forever", "-shared", "-noremote"]
        command += ["-rfbauth", str(password)] if password else ["-nopw"]
    else:
        server = executable(values["WEBSOCKIFY_BIN"])
        password_path(values)
        web = Path(values["NOVNC_WEB_DIR"])
        if not (web / "vnc.html").is_file():
            raise ConfigError("NOVNC_WEB_DIR must contain vnc.html")
        # A saved password does not prove the already-running VNC server uses it.
        deadline = time.monotonic() + 15
        while True:
            try:
                check_vnc_auth(values)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise ConfigError("VNC did not become ready within 15 seconds") from None
                time.sleep(0.2)
        command = [server, "--web", str(web), endpoint(values["NOVNC_HOST"], values["NOVNC_PORT"]),
                   endpoint("127.0.0.1", values["VNC_PORT"])]
    os.execvpe(command[0], command, environment)


def endpoint(host, port):
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def listeners():
    result = subprocess.run(["ss", "-H", "-ltn"], check=True, capture_output=True, text=True, timeout=5)
    found = {}
    for line in result.stdout.splitlines():
        columns = line.split()
        if len(columns) < 5:
            raise ConfigError("could not parse ss listener output")
        host, port = columns[3].rsplit(":", 1)
        if port.isdecimal():
            found.setdefault(port, set()).add(host.strip("[]"))
    return found


def fetch_json(url):
    # Do not let a user's proxy environment send authenticated CDP requests off-host.
    with build_opener(ProxyHandler({})).open(url, timeout=5) as response:
        return json.loads(response.read(1024 * 1024))


def vnc_security_types(host, port):
    def receive(connection, length):
        data = b""
        while len(data) < length:
            chunk = connection.recv(length - len(data))
            if not chunk:
                raise ConfigError("VNC closed during its handshake")
            data += chunk
        return data

    with socket.create_connection((host, int(port)), timeout=5) as connection:
        banner = receive(connection, 12)
        if banner not in (b"RFB 003.007\n", b"RFB 003.008\n"):
            raise ConfigError("VNC did not advertise RFB 3.7 or 3.8")
        connection.sendall(banner)
        count = receive(connection, 1)[0]
        if count == 0:
            raise ConfigError("VNC rejected the handshake")
        return set(receive(connection, count))


def check_vnc_auth(values):
    password = password_path(values)
    security = vnc_security_types("127.0.0.1", values["VNC_PORT"])
    if password:
        if 2 not in security or 1 in security:
            raise ConfigError("VNC password authentication is not enforced; restart VNC")
    elif 1 not in security:
        raise ConfigError("loopback VNC authentication differs from config; restart VNC")


def health():
    values = load_config()
    failures = []

    def check(label, operation):
        try:
            operation()
            print(f"ok: {label}")
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            failures.append(label)
            print(f"fail: {label}: {exc}", file=sys.stderr)

    def require(condition, message):
        if not condition:
            raise ConfigError(message)

    for service in SERVICES:
        check(f"{service} active", lambda service=service: subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", service], check=True, timeout=5))
    try:
        bound = listeners()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        bound = {}
        failures.append("listener inventory")
        print(f"fail: cannot inspect listeners: {exc}", file=sys.stderr)
    for name, host in (("CDP", "127.0.0.1"), ("VNC", "127.0.0.1"), ("NOVNC", values["NOVNC_HOST"])):
        port = values[f"{name}_PORT"]
        # Check local addresses, not peer columns or arbitrary process output.
        check(f"{name} listener bound only to {endpoint(host, port)}",
              lambda port=port, host=host: require(bound.get(port) == {host}, "missing or unexpected bind address"))

    def cdp_check():
        data = fetch_json(f"http://127.0.0.1:{values['CDP_PORT']}/json/version")
        require(isinstance(data, dict) and isinstance(data.get("Browser"), str) and bool(data["Browser"]),
                "missing browser version")
        require(isinstance(data.get("webSocketDebuggerUrl"), str), "missing CDP websocket URL")
        url = urlsplit(data["webSocketDebuggerUrl"])
        require(url.scheme == "ws" and url.hostname in ("127.0.0.1", "localhost", "::1")
                and url.port == int(values["CDP_PORT"]) and url.path.startswith("/devtools/browser/"),
                "invalid or non-loopback CDP websocket URL")

    def novnc_check():
        url = f"http://{endpoint(values['NOVNC_HOST'], values['NOVNC_PORT'])}/vnc.html"
        with build_opener(ProxyHandler({})).open(url, timeout=5) as response:
            require(response.status == 200 and b"<html" in response.read(65536).lower(), "noVNC page unavailable")

    def profile_check():
        path = Path(values["CHROME_PROFILE_DIR"])
        info = path.stat()
        require(path.is_dir() and not path.is_symlink() and info.st_uid == os.getuid() and not info.st_mode & 0o077,
                "browser profile must be owned by you with mode 700")

    check("CDP version and websocket URL", cdp_check)
    check("noVNC web page", novnc_check)
    check("VNC authentication matches config", lambda: check_vnc_auth(values))
    check("private browser profile", profile_check)
    if shutil.which("hermes"):
        try:
            result = subprocess.run(["hermes", "config", "get", "browser.cdp_url"],
                                    capture_output=True, text=True, timeout=5, check=True)
            if result.stdout.strip() != f"http://127.0.0.1:{values['CDP_PORT']}":
                print("warn: Hermes browser.cdp_url differs from the local CDP endpoint", file=sys.stderr)
        except (OSError, subprocess.SubprocessError):
            print("warn: could not read Hermes browser.cdp_url", file=sys.stderr)
    else:
        print("warn: Hermes CLI unavailable; skipping integration config check", file=sys.stderr)
    if failures:
        print(f"fail: {len(failures)} health check(s) failed", file=sys.stderr)
        return 1
    print("ok: health checks passed")
    return 0


def systemd_quote(value, command=False):
    if any(ord(char) < 32 or ord(char) == 127 for char in str(value)):
        raise ConfigError("systemd paths must not contain control characters")
    value = str(value).replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"')
    if command:
        value = value.replace("$", "$$")
    return f'"{value}"'


def render_units(source, destination, runtime, config):
    destination.mkdir(parents=True, exist_ok=True)
    for template in sorted(source.glob("hermes-browser*")):
        content = template.read_text().replace("@RUNTIME@", systemd_quote(runtime, command=True))
        content = content.replace("@CONFIG@", systemd_quote(config))
        atomic_write(destination / template.name, content, mode=0o644)


def install():
    repository = Path(__file__).resolve().parent.parent
    config = config_path()
    directory = config.parent
    secure_directory(directory)
    if not config.exists():
        values = defaults()
        for candidate in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
            if shutil.which(candidate):
                values["CHROME_BIN"] = shutil.which(candidate)
                break
        # Snap confines Chromium's profile access to its own writable home area.
        if "/snap/" in values["CHROME_BIN"] or values["CHROME_BIN"].endswith("/chromium-browser"):
            values["CHROME_PROFILE_DIR"] = str(Path.home() / "snap/chromium/common/hermes-shared-browser")
        for candidate in ("/usr/share/novnc", "/usr/share/noVNC", "/opt/novnc"):
            if (Path(candidate) / "vnc.html").is_file():
                values["NOVNC_WEB_DIR"] = candidate
                break
        content = "# KEY=VALUE data; quote paths containing spaces. Shell commands are never evaluated.\n"
        content += "".join(f"{key}={shlex.quote(value) if value else ''}\n" for key, value in values.items())
        atomic_write(config, content)
    else:
        load_config(config)
    secure_directory(Path(load_config(config)["CHROME_PROFILE_DIR"]))
    runtime = directory / "browser_runtime.py"
    atomic_write(runtime, Path(__file__).read_text())
    root = Path(os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config"))
    units = root / "systemd/user"
    render_units(repository / "systemd/user", units, runtime, config)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
    print(f"Installed user units to: {units}\nConfig file: {config}")
    print("Next: make start && make health")
    print("Before remote access: make set-vnc-password, then choose a private NOVNC_HOST.")
    print("Set Hermes browser.cdp_url to http://127.0.0.1:<CDP_PORT>.")


def set_password():
    config = config_path()
    # Require an installed config; a password-only env must not mask missing defaults.
    load_config(config)
    secure_directory(config.parent)
    server = executable("x11vnc")
    fd, temporary = tempfile.mkstemp(prefix=".vnc-pass.", dir=config.parent)
    os.close(fd)
    password = config.parent / "vnc.pass"
    try:
        os.umask(0o077)
        subprocess.run([server, "-norc", "-storepasswd", temporary], check=True)
        private_file(Path(temporary))
        if Path(temporary).stat().st_size != 8:
            raise ConfigError("VNC password was not saved; existing password and config kept")
        os.replace(temporary, password)
    finally:
        Path(temporary).unlink(missing_ok=True)
    lines = [line for line in config.read_text().splitlines()
             if not re.match(r"\s*VNC_PASSWORD_FILE\s*=", line)]
    lines.append(f"VNC_PASSWORD_FILE={shlex.quote(str(password))}")
    atomic_write(config, "\n".join(lines) + "\n")
    print(f"ok: VNC password stored at {password}")
    print("Restart VNC/noVNC: systemctl --user restart hermes-browser-vnc.service hermes-browser-novnc.service")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="action", required=True)
    subcommands.add_parser("install")
    subcommands.add_parser("set-password")
    subcommands.add_parser("health")
    runner = subcommands.add_parser("launch")
    runner.add_argument("component", choices=("xvfb", "chromium", "vnc", "novnc"))
    renderer = subcommands.add_parser("render-units")
    renderer.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        if args.action == "install":
            install()
        elif args.action == "set-password":
            set_password()
        elif args.action == "health":
            return health()
        elif args.action == "render-units":
            render_units(Path(__file__).resolve().parent.parent / "systemd/user", args.destination,
                         Path(__file__).resolve(), config_path())
        else:
            launch(args.component)
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"fail: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

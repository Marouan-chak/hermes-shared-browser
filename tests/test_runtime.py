import contextlib
import importlib.util
import io
import os
from pathlib import Path
import shlex
import socket
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("browser_runtime", REPO / "scripts/browser_runtime.py")
runtime = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime)


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="hermes-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = self.root / "config with spaces & 'quotes' % and $/env"
        self.config.parent.mkdir(mode=0o700)
        self.environment = patch.dict(os.environ, {"HERMES_BROWSER_CONFIG": str(self.config)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.write_config()

    def write_config(self, content=""):
        runtime.atomic_write(self.config, content)

    def password(self):
        path = self.config.parent / "vnc.pass"
        path.write_bytes(b"fixture!")
        path.chmod(0o600)
        return path

    def capture_launch(self, component):
        with patch.object(runtime, "executable", side_effect=lambda value: value), \
                patch.object(runtime, "wait_for_display"), patch.object(runtime.os, "execvpe") as execute:
            runtime.launch(component)
            return execute.call_args.args

    def test_defaults_for_partial_configs(self):
        self.write_config("VNC_PASSWORD_FILE=\nCDP_PORT=12345\n")
        values = runtime.load_config()
        self.assertEqual(values["CDP_PORT"], "12345")
        self.assertEqual(values["DISPLAY_NUM"], "99")

    def test_config_is_data_not_shell_code(self):
        marker = self.root / "executed"
        value = f"$(touch {marker})"
        self.write_config(f"CHROME_BIN={shlex.quote(value)}\n")
        self.assertEqual(runtime.load_config()["CHROME_BIN"], value)
        self.assertFalse(marker.exists())
        self.write_config(f"CDP_PORT=9222; touch {marker}\n")
        with self.assertRaises(runtime.ConfigError):
            runtime.load_config()
        self.assertFalse(marker.exists())

    def test_home_paths_and_quoted_special_characters(self):
        profile = self.root / "profile with spaces & 'quotes' $ %"
        self.write_config(f"CHROME_PROFILE_DIR={shlex.quote(str(profile))}\n")
        self.assertEqual(runtime.load_config()["CHROME_PROFILE_DIR"], str(profile))
        for prefix in ("$HOME/", "${HOME}/", "~/"):
            self.write_config(f"CHROME_PROFILE_DIR='{prefix}profile'\n")
            self.assertEqual(runtime.load_config()["CHROME_PROFILE_DIR"], str(Path.home() / "profile"))

    def test_invalid_settings_fail_before_launch(self):
        invalid = ("CDP_HOST=0.0.0.0", "VNC_HOST=10.0.0.1", "NOVNC_HOST=0.0.0.0",
                   "NOVNC_HOST=::", "NOVNC_HOST=8.8.8.8", "NOVNC_HOST=example.com",
                   "NOVNC_HOST=100.128.0.1", "NOVNC_HOST=172.32.0.1", "CDP_PORT=0",
                   "CDP_PORT=65536", "CDP_PORT=hello", "CDP_PORT=5900", "DISPLAY_NUM=-1",
                   "DISPLAY_NUM=99999", "SCREEN_GEOMETRY=bad", "CHROME_PROFILE_DIR=relative",
                   "UNKNOWN_KEY=value", "CHROME_BIN='unterminated", "export CDP_PORT=12345")
        for setting in invalid:
            with self.subTest(setting=setting):
                self.write_config(setting + "\n")
                with self.assertRaises(runtime.ConfigError):
                    runtime.load_config()

    def test_only_private_novnc_addresses_are_accepted(self):
        for address in ("127.0.0.1", "localhost", "::1", "10.0.0.1", "172.16.0.1",
                        "192.168.0.1", "100.64.0.1", "100.127.255.254", "fd00::1"):
            with self.subTest(address=address):
                self.write_config(f"NOVNC_HOST={address}\n")
                runtime.load_config()

    def test_unsafe_config_permissions_are_rejected(self):
        self.config.chmod(0o644)
        with self.assertRaisesRegex(runtime.ConfigError, "mode 600"):
            runtime.load_config()

    def test_remote_novnc_requires_password(self):
        self.write_config("NOVNC_HOST=10.0.0.1\n")
        with self.assertRaisesRegex(runtime.ConfigError, "requires a VNC password"):
            runtime.password_path(runtime.load_config())

    def test_missing_configured_password_never_becomes_nopw(self):
        self.write_config(f"VNC_PASSWORD_FILE={shlex.quote(str(self.root / 'missing'))}\n")
        with patch.object(runtime, "executable", side_effect=lambda value: value), \
                patch.object(runtime.os, "execvpe") as execute:
            with self.assertRaisesRegex(runtime.ConfigError, "refusing unauthenticated"):
                runtime.launch("vnc")
            execute.assert_not_called()

    def test_password_must_be_private_and_valid(self):
        path = self.password()
        self.write_config(f"VNC_PASSWORD_FILE={shlex.quote(str(path))}\n")
        values = runtime.load_config()
        self.assertEqual(runtime.password_path(values), path)
        path.chmod(0o644)
        with self.assertRaises(runtime.ConfigError):
            runtime.password_path(values)
        path.chmod(0o600)
        path.write_bytes(b"")
        with self.assertRaisesRegex(runtime.ConfigError, "invalid VNC password"):
            runtime.password_path(values)

    def test_chromium_gets_real_display_and_private_profile(self):
        profile = self.root / "profile with spaces"
        self.write_config(f"DISPLAY_NUM=123\nCHROME_PROFILE_DIR={shlex.quote(str(profile))}\n")
        _, command, environment = self.capture_launch("chromium")
        self.assertEqual(environment["DISPLAY"], ":123")
        self.assertIn(f"--user-data-dir={profile}", command)
        self.assertIn("--remote-debugging-address=127.0.0.1", command)
        self.assertNotIn("--no-sandbox", command)
        self.assertNotIn("--password-store=basic", command)
        self.assertEqual(profile.stat().st_mode & 0o777, 0o700)

    def test_xvfb_uses_cookie_authentication(self):
        with patch.object(runtime.subprocess, "run") as run:
            _, command, environment = self.capture_launch("xvfb")
        self.assertIn("-auth", command)
        self.assertNotIn("-ac", command)
        self.assertIn("tcp", command)
        self.assertEqual(Path(environment["XAUTHORITY"]).stat().st_mode & 0o777, 0o600)
        self.assertRegex(run.call_args.kwargs["input"], r"add :99 \. [0-9a-f]{32}\n")

    def test_vnc_disables_ipv6_and_user_rc_overrides(self):
        _, command, _ = self.capture_launch("vnc")
        self.assertIn("-no6", command)
        self.assertIn("-noipv6", command)
        self.assertEqual(command[command.index("-rfbportv6") + 1], "-1")
        self.assertIn("-norc", command)
        self.assertIn("-noremote", command)
        self.assertIn("-nopw", command)

    def test_vnc_passes_a_password_path_as_one_argument(self):
        path = self.password()
        self.write_config(f"VNC_PASSWORD_FILE={shlex.quote(str(path))}\n")
        _, command, _ = self.capture_launch("vnc")
        self.assertIn(str(path), command)
        self.assertIn("-rfbauth", command)
        self.assertNotIn("-nopw", command)

    def test_novnc_refuses_stale_passwordless_vnc(self):
        path = self.password()
        web = self.root / "web"
        web.mkdir()
        (web / "vnc.html").write_text("<html></html>")
        self.write_config(f"NOVNC_HOST=10.0.0.1\nVNC_PASSWORD_FILE={shlex.quote(str(path))}\n"
                          f"NOVNC_WEB_DIR={shlex.quote(str(web))}\n")
        with patch.object(runtime, "vnc_security_types", return_value={1}), \
                patch.object(runtime, "executable", side_effect=lambda value: value), \
                patch.object(runtime.os, "execvpe") as execute:
            with self.assertRaisesRegex(runtime.ConfigError, "not enforced"):
                runtime.launch("novnc")
            execute.assert_not_called()

    def test_listener_checks_use_local_column_and_exact_ports(self):
        output = ("LISTEN 0 5 0.0.0.0:9222 127.0.0.1:9222\n"
                  "LISTEN 0 5 127.0.0.1:19222 0.0.0.0:*\n"
                  "LISTEN 0 5 [::]:5900 [::]:*\n")
        with patch.object(runtime.subprocess, "run", return_value=subprocess.CompletedProcess([], 0, output)):
            bound = runtime.listeners()
        self.assertEqual(bound["9222"], {"0.0.0.0"})
        self.assertEqual(bound["5900"], {"::"})
        self.assertEqual(bound["19222"], {"127.0.0.1"})

    def health_result(self, bound, cdp=None, security=None, page=b"<html></html>"):
        profile = self.root / "private profile"
        profile.mkdir(mode=0o700, exist_ok=True)
        values = runtime.load_config()
        values["CHROME_PROFILE_DIR"] = str(profile)
        cdp = cdp if cdp is not None else {"Browser": "Chrome/fixture",
                    "webSocketDebuggerUrl": "ws://127.0.0.1:9222/devtools/browser/fixture"}
        response = io.BytesIO(page)
        response.status = 200
        opener = unittest.mock.Mock()
        opener.open.return_value = response
        with patch.object(runtime, "load_config", return_value=values), \
                patch.object(runtime.subprocess, "run"), patch.object(runtime, "listeners", return_value=bound), \
                patch.object(runtime, "fetch_json", return_value=cdp), \
                patch.object(runtime, "build_opener", return_value=opener), \
                patch.object(runtime, "vnc_security_types", return_value=security or {1}), \
                patch.object(runtime.shutil, "which", return_value=None), \
                contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return runtime.health()

    def good_listeners(self):
        return {port: {"127.0.0.1"} for port in ("9222", "5900", "6080")}

    def test_missing_and_wildcard_listeners_fail_health(self):
        self.assertEqual(self.health_result(self.good_listeners()), 0)
        self.assertEqual(self.health_result({}), 1)
        for port in ("9222", "5900", "6080"):
            bound = self.good_listeners()
            bound[port].add("::")
            with self.subTest(port=port):
                self.assertEqual(self.health_result(bound), 1)

    def test_wrong_cdp_websocket_urls_fail_health(self):
        for url in ("ws://10.0.0.1:9222/devtools/browser/fixture",
                    "ws://127.0.0.1:12345/devtools/browser/fixture", "http://127.0.0.1:9222", None):
            with self.subTest(url=url):
                self.assertEqual(self.health_result(self.good_listeners(),
                    {"Browser": "Chrome/fixture", "webSocketDebuggerUrl": url}), 1)

    def test_non_html_novnc_page_fails_health(self):
        self.assertEqual(self.health_result(self.good_listeners(), page=b"unrelated server"), 1)

    def test_stale_passwordless_vnc_fails_health(self):
        path = self.password()
        self.write_config(f"VNC_PASSWORD_FILE={shlex.quote(str(path))}\n")
        self.assertEqual(self.health_result(self.good_listeners(), security={2}), 0)
        self.assertEqual(self.health_result(self.good_listeners(), security={1, 2}), 1)

    def test_password_prompt_failure_preserves_config_and_password(self):
        password = self.password()
        original = self.config.read_bytes()
        with patch.object(runtime, "executable", return_value="x11vnc"), \
                patch.object(runtime.subprocess, "run", side_effect=subprocess.CalledProcessError(1, [])):
            with self.assertRaises(subprocess.CalledProcessError):
                runtime.set_password()
        self.assertEqual(self.config.read_bytes(), original)
        self.assertEqual(password.read_bytes(), b"fixture!")
        self.assertFalse(list(self.config.parent.glob(".vnc-pass.*")))

    def test_password_updates_handle_spaces_ampersands_and_duplicate_keys(self):
        self.write_config("# existing comment\nCDP_PORT=12345\nVNC_PASSWORD_FILE=\n VNC_PASSWORD_FILE =\n")

        def store(command, **kwargs):
            Path(command[-1]).write_bytes(b"fixture!")

        with patch.object(runtime, "executable", return_value="x11vnc"), \
                patch.object(runtime.subprocess, "run", side_effect=store), contextlib.redirect_stdout(io.StringIO()):
            runtime.set_password()
        self.assertEqual(self.config.read_text().count("VNC_PASSWORD_FILE="), 1)
        values = runtime.load_config()
        self.assertEqual(values["CDP_PORT"], "12345")
        self.assertEqual(runtime.password_path(values), self.config.parent / "vnc.pass")

    def test_password_before_install_does_not_create_partial_config(self):
        self.config.unlink()
        with self.assertRaisesRegex(runtime.ConfigError, "run make install"):
            runtime.set_password()
        self.assertFalse(self.config.exists())

    def test_install_is_idempotent_and_services_survive_repo_moves(self):
        profile = self.root / "profile"
        self.write_config(f"CDP_PORT=12345\nCHROME_PROFILE_DIR={shlex.quote(str(profile))}\n")
        original = self.config.read_bytes()
        config_root = self.root / "xdg with % and $"
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": str(config_root)}), \
                patch.object(runtime.subprocess, "run"), contextlib.redirect_stdout(io.StringIO()):
            runtime.install()
            runtime.install()
        self.assertEqual(self.config.read_bytes(), original)
        copied = self.config.parent / "browser_runtime.py"
        self.assertTrue(copied.is_file())
        units = list((config_root / "systemd/user").glob("*"))
        self.assertEqual(len(units), 5)
        for unit in units:
            text = unit.read_text()
            self.assertNotIn("@CONFIG@", text)
            self.assertNotIn("@RUNTIME@", text)
            self.assertNotIn(str(REPO), text)
        self.assertEqual(profile.stat().st_mode & 0o777, 0o700)

    def test_relative_config_roots_are_rejected(self):
        with patch.dict(os.environ, {"XDG_CONFIG_HOME": "relative"}):
            with self.assertRaises(runtime.ConfigError):
                runtime.config_path()

    def test_vnc_handshake_handles_fragmented_packets(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen()
        self.addCleanup(server.close)

        def serve():
            with server.accept()[0] as connection:
                connection.sendall(b"RFB ")
                connection.sendall(b"003.008\n")
                data = b""
                while len(data) < 12:
                    data += connection.recv(12 - len(data))
                connection.sendall(b"\x01\x02")

        thread = threading.Thread(target=serve, daemon=True)
        thread.start()
        self.assertEqual(runtime.vnc_security_types("127.0.0.1", server.getsockname()[1]), {2})
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()

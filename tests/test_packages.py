import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


REPO = Path(__file__).resolve().parents[1]


@unittest.skipUnless(Path("/etc/debian_version").exists(), "Debian/Ubuntu package installer")
class PackageInstallerTests(unittest.TestCase):
    def run_installer(self, candidates, fail_install=False):
        with tempfile.TemporaryDirectory(prefix="hermes-packages-test-") as temporary:
            root = Path(temporary)
            log = root / "calls.jsonl"
            programs = {
                "apt-cache": f"import sys\nversions = {candidates!r}\nprint('  Candidate: ' + versions.get(sys.argv[-1], '(none)'))\n",
                "apt-get": "import json, os, sys\nwith open(os.environ['HERMES_TEST_APT_LOG'], 'a') as stream:\n    stream.write(json.dumps(sys.argv[1:]) + '\\n')\n"
                           + ("sys.exit(1 if 'install' in sys.argv else 0)\n" if fail_install else ""),
                "sudo": "import os, sys\nos.execvp(sys.argv[1], sys.argv[1:])\n",
            }
            for name, source in programs.items():
                path = root / name
                path.write_text(f"#!{sys.executable}\n" + source)
                path.chmod(0o700)
            result = subprocess.run(["bash", str(REPO / "scripts/install-debian-packages.sh")],
                env=dict(os.environ, PATH=f"{root}:{os.environ['PATH']}", HERMES_TEST_APT_LOG=str(log)),
                capture_output=True, text=True, timeout=10)
            calls = [json.loads(line) for line in log.read_text().splitlines()]
            return result, calls

    def test_chromium_includes_sandbox_and_runtime_dependencies(self):
        result, calls = self.run_installer({"chromium": "1.0", "chromium-sandbox": "1.0"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls[0], ["update"])
        for package in ("chromium", "chromium-sandbox", "python3", "xauth", "x11-utils", "iproute2"):
            self.assertIn(package, calls[1])

    def test_unavailable_chromium_falls_back_to_browser(self):
        result, calls = self.run_installer({"chromium-browser": "1.0"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("chromium-browser", calls[1])
        self.assertNotIn("chromium", calls[1])

    def test_missing_candidates_and_failed_install_do_not_claim_success(self):
        result, calls = self.run_installer({})
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls, [["update"]])
        self.assertNotIn("dependencies installed", result.stdout)
        result, _ = self.run_installer({"chromium": "1.0"}, fail_install=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("dependencies installed", result.stdout)


if __name__ == "__main__":
    unittest.main()

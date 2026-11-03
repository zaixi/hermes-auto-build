"""Offline regressions for browser markers and npm command visibility."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


class ImageToolTests(unittest.TestCase):
    def adapter(self):
        source = ROOT / "scripts/image_browser.py"
        self.assertTrue(source.is_file(), "Missing shared browser-marker selection")
        spec = importlib.util.spec_from_file_location("image_browser", source)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def fixture(self, root):
        binary = root / "managed-chromium"
        binary.write_text("#!/bin/sh\nprintf 'Chromium fixture\\n'\n")
        binary.chmod(0o755)
        return binary

    def test_current_and_legacy_markers_are_supported_without_a_download(self):
        adapter = self.adapter()
        for name in ("chromium-executable-path", "agent-browser-executable-path"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                binary = self.fixture(root)
                (root / name).write_text(str(binary) + "\n")
                self.assertEqual(adapter.browser_path(root, system_browser=None), binary)

    def test_current_marker_wins_over_legacy(self):
        adapter = self.adapter()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = self.fixture(root)
            (root / "chromium-executable-path").write_text(str(binary))
            (root / "agent-browser-executable-path").write_text("/obsolete/browser")
            self.assertEqual(adapter.browser_path(root, system_browser=None), binary)

    def test_invalid_marker_fails_closed_instead_of_downloading_another_browser(self):
        adapter = self.adapter()
        for name in ("chromium-executable-path", "agent-browser-executable-path"):
            for value in ("", "relative/chrome", "/does/not/exist"):
                with self.subTest(name=name, value=value), tempfile.TemporaryDirectory() as directory:
                    root = Path(directory)
                    (root / name).write_text(value)
                    with self.assertRaisesRegex(ValueError, "Invalid.*marker"):
                        adapter.browser_path(root, system_browser=None)

    def test_nonexecutable_marker_is_rejected(self):
        adapter = self.adapter()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = self.fixture(root)
            binary.chmod(0o644)
            (root / "chromium-executable-path").write_text(str(binary))
            with self.assertRaises(ValueError):
                adapter.browser_path(root, system_browser=None)

    def test_no_marker_uses_system_browser_or_reports_missing(self):
        adapter = self.adapter()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertIsNone(adapter.browser_path(root, system_browser=None))
            binary = self.fixture(root)
            self.assertEqual(adapter.browser_path(root, system_browser=str(binary)), binary)

    def test_link_cli_reuses_browser_and_executes_it(self):
        self.adapter()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            binary = self.fixture(root)
            (root / "chromium-executable-path").write_text(str(binary))
            link = root / "hermes-chromium"
            subprocess.run(["python3", str(ROOT / "scripts/image_browser.py"),
                            "--marker-dir", str(root), "--link", str(link)], check=True)
            self.assertEqual(link.resolve(), binary)
            result = subprocess.run([str(link), "--version"], check=True, capture_output=True, text=True)
            self.assertIn("Chromium fixture", result.stdout)

    def test_dockerfile_installs_npm_commands_into_stable_runtime_path(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("npm install -g --prefix /usr/local", dockerfile)
        self.assertNotIn("agent-browser install", dockerfile)
        self.assertIn("AGENT_BROWSER_EXECUTABLE_PATH=/usr/local/bin/hermes-chromium", dockerfile)
        self.assertIn("image_browser.py", dockerfile)
        workflow = (ROOT / ".github/workflows/build.yml").read_text()
        self.assertIn("test_image_tools.py", workflow)

    def test_smoke_checks_cli_and_browser_as_part_of_build_verification(self):
        smoke = (ROOT / "scripts/verify_image_dependencies.py").read_text()
        self.assertIn("def verify_cli_tools", smoke)
        self.assertIn('"agent-browser"', smoke)
        self.assertIn('"lark-cli"', smoke)
        self.assertIn('"--session"', smoke)
        self.assertIn('"get", "title"', smoke)
        self.assertIn('"close"', smoke)
        self.assertIn('"-lc"', smoke)
        self.assertIn("verify_cli_tools()", smoke)

    def smoke_adapter(self):
        with patch.object(sys, "path", [str(ROOT / "scripts"), *sys.path]):
            spec = importlib.util.spec_from_file_location(
                "image_smoke", ROOT / "scripts/verify_image_dependencies.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module

    def test_smoke_reuses_session_and_closes_on_success_or_failure(self):
        smoke = self.smoke_adapter()
        for failure in (None, "open", "get", "wrong-title"):
            with self.subTest(failure=failure):
                calls = []

                def run(command, **kwargs):
                    calls.append(command)
                    if "--session" in command:
                        if failure in ("open", "get") and command[5] == failure:
                            raise subprocess.CalledProcessError(1, command)
                        title = "wrong" if failure == "wrong-title" else "hermes-image-smoke"
                        return subprocess.CompletedProcess(command, 0, stdout=title)
                    return subprocess.CompletedProcess(command, 0)

                with patch.object(smoke.shutil, "which", return_value="/usr/local/bin/cli"), \
                        patch.object(smoke.os, "access", return_value=True), \
                        patch.dict(os.environ, {"AGENT_BROWSER_EXECUTABLE_PATH": "/image/chrome"}), \
                        patch.object(smoke.subprocess, "run", side_effect=run):
                    if failure:
                        with self.assertRaises((subprocess.CalledProcessError, RuntimeError)):
                            smoke.verify_cli_tools()
                    else:
                        smoke.verify_cli_tools()
                browser_calls = [command for command in calls if "--session" in command]
                self.assertEqual(browser_calls[-1][5:], ["close"])
                self.assertEqual(len({tuple(command[:5]) for command in browser_calls}), 1)
                self.assertEqual(browser_calls[0][3:5], ["--args", "--no-sandbox"])
                self.assertIn(["/image/chrome", "--version"], calls)
                self.assertTrue(any(command[:2] == ["/bin/sh", "-lc"] for command in calls))

    def test_smoke_rejects_missing_cli_before_launching_browser(self):
        smoke = self.smoke_adapter()
        with patch.object(smoke.shutil, "which", return_value=None), \
                patch.object(smoke.subprocess, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "Missing runtime CLI"):
                smoke.verify_cli_tools()
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()

"""Opt-in real uv regression against the supported upstream release checkout.

HERMES_RESOLVER_SOURCE=/path/to/supported-release HERMES_TEST_UV=/path/to/pinned/uv \
    python3 -m unittest discover -s tests -p test_image_resolution_live.py -v

Only temporary copies are modified. Downloads metadata, not image layers.
"""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(os.environ.get("HERMES_RESOLVER_SOURCE") and os.environ.get("HERMES_TEST_UV"),
                     "requires an upstream checkout and its pinned uv (network integration)")
class RealResolverTests(unittest.TestCase):
    def test_current_custom_image_resolves_without_dropping_whisper(self):
        source = Path(os.environ["HERMES_RESOLVER_SOURCE"])
        upstream_lock = tomllib.loads((source / "uv.lock").read_text())
        whisper_versions = {package["version"] for package in upstream_lock["package"]
                            if package["name"] == "faster-whisper"}
        self.assertTrue(whisper_versions, "The upstream release must declare its Whisper pin")
        spec = importlib.util.spec_from_file_location("image_deps", ROOT / "scripts/install_image_dependencies.py")
        assert spec is not None and spec.loader is not None
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            for name in ("pyproject.toml", "uv.lock", "setup.py", "README.md", "LICENSE"):
                if (source / name).is_file():
                    shutil.copy2(source / name, project / name)
            requirements = [line.strip() for line in (ROOT / "requirements-custom.txt").read_text().splitlines()
                            if line.strip() and not line.startswith("#")]
            adapter.add_custom_extra(project / "pyproject.toml", requirements)
            adapter.constrain_image_resolution(project / "pyproject.toml")
            command = [os.environ["HERMES_TEST_UV"], "lock", "--project", str(project), "--python", sys.executable]
            result = subprocess.run(command, capture_output=True, text=True, timeout=180)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            lock = tomllib.loads((project / "uv.lock").read_text())
            packages = {package["name"]: package for package in lock["package"]}
            self.assertIn(packages["faster-whisper"]["version"], whisper_versions)
            self.assertIn("onnxruntime", packages)
            for name in ("pandas", "openpyxl", "hermes-keenable-web", "hindsight-client", "hindsight-embed",
                         "lark-oapi", "edge-tts", "pilk"):
                self.assertIn(name, packages)
            print(f"Real uv resolver: {len(packages)} packages; whisper + all custom dependencies retained")

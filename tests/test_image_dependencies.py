"""Offline regression tests for the custom image's dependency build."""
import importlib.util
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install_image_dependencies.py"


class ImageDependencyTests(unittest.TestCase):
    def load_adapter(self):
        self.assertTrue(SCRIPT.is_file(), "Missing PM-aware image dependency adapter")
        spec = importlib.util.spec_from_file_location("image_deps", SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_custom_extra_extends_upstream_without_changing_core_pins(self):
        adapter = self.load_adapter()
        original = '''[project]
name = "hermes-agent"
dependencies = ["httpx==0.28.1"]
[project.optional-dependencies]
all = ["hermes-agent[web]"]
web = ["aiohttp==3.14.3"]
feishu = ["lark-oapi==1.6.8", "qrcode==7.4.2"]
edge-tts = ["edge-tts==7.2.7"]
silk = ["pilk==0.2.4"]
[tool.uv]
exclude-newer = "3 days"
'''
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "pyproject.toml"
            project.write_text(original)
            adapter.add_custom_extra(project, ["pandas", "hindsight-client>=0.10.1,<1"])
            result = tomllib.loads(project.read_text())
        self.assertEqual(result["project"]["dependencies"], ["httpx==0.28.1"])
        extras = result["project"]["optional-dependencies"]
        self.assertEqual(extras["web"], ["aiohttp==3.14.3"])
        self.assertEqual(extras["image-custom"], ["pandas", "hindsight-client>=0.10.1,<1"])
        self.assertEqual(result["tool"]["uv"]["exclude-newer"], "3 days")

    def test_build_command_keeps_base_selection_and_uses_pm(self):
        adapter = self.load_adapter()
        source = Path("/image/hermes")
        command = adapter.pm_build_command(source, ["all", "matrix", "otlp"])
        self.assertEqual(command[:3], ["python3", "-m", "pm.build_env"])
        self.assertIn("--sealed", command)
        self.assertIn("--record-selection", command)
        self.assertIn("--resolve", command)
        self.assertIn("--no-install-project", command)
        self.assertEqual(command[command.index("--out") + 1], str(source / ".venv"))
        extras = {command[i + 1] for i, value in enumerate(command) if value == "--extra"}
        self.assertEqual(extras, {"all", "matrix", "otlp", "feishu", "edge-tts", "silk", "image-custom"})

    def test_selection_is_read_or_reported_absent_never_guessed(self):
        adapter = self.load_adapter()
        with tempfile.TemporaryDirectory() as temp:
            facts = Path(temp) / "facts.json"
            facts.write_text('{"schema":1,"packages":{"venv":{"stamp":"legacy"}}}')
            self.assertIsNone(adapter.recorded_selection(facts), "v0.21.6-style base has no selection")
            facts.write_text('{"schema":1,"packages":{}}')
            self.assertIsNone(adapter.recorded_selection(facts))
            for invalid in ('{"packages":{"venv":{"extras":[]}}}',
                            '{"packages":{"venv":{"extras":[1]}}}',
                            '{"packages":{"venv":{"extras":"all"}}}'):
                with self.subTest(invalid=invalid):
                    facts.write_text(invalid)
                    with self.assertRaisesRegex(ValueError, "selection"):
                        adapter.recorded_selection(facts)
            facts.write_text('{"schema":1,"packages":{"venv":{"extras":["all","matrix"]}}}')
            self.assertEqual(adapter.recorded_selection(facts), ["all", "matrix"])

    def test_unrecorded_pm_base_is_refused_with_the_real_reason(self):
        import runpy
        import sys
        import types

        self.load_adapter()
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "hermes"
            (source / "pm").mkdir(parents=True)
            (source / "pm/build_env.py").write_text("")  # a PM base without --record-selection
            facts = Path(temp) / "facts.json"
            facts.write_text('{"schema":1,"packages":{"venv":{"stamp":"0ef3f43d"}}}')
            (source / "pyproject.toml").write_text(
                '[project.optional-dependencies]\nfeishu = ["lark-oapi==1.6.8"]\n'
                'edge-tts = ["edge-tts==7.2.7"]\nsilk = ["pilk==0.2.4"]\n')
            requirements = Path(temp) / "requirements-custom.txt"
            requirements.write_text("pandas\n")
            pm_package = types.ModuleType("pm")
            pm_package.__path__ = [str(source / "pm")]
            pm_paths = types.ModuleType("pm.paths")
            setattr(pm_paths, "facts_path", lambda: facts)
            argv = ["install_image_dependencies.py", "--source", str(source),
                    "--requirements", str(requirements)]
            with patch.dict(sys.modules, {"pm": pm_package, "pm.paths": pm_paths}), \
                    patch("sys.argv", argv), self.assertRaisesRegex(ValueError, "record-selection"):
                runpy.run_path(str(SCRIPT), run_name="__main__")

    def test_adapter_has_a_real_cli(self):
        import subprocess
        result = subprocess.run(["python3", str(SCRIPT), "--help"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("--requirements", result.stdout)

    def test_custom_packages_are_unpinned_except_plugin_api_bounds(self):
        manifest = ROOT / "requirements-custom.txt"
        self.assertTrue(manifest.is_file(), "Missing explicit custom dependency manifest")
        requirements = [line.strip() for line in manifest.read_text().splitlines() if line.strip() and not line.startswith("#")]
        self.assertEqual(set(requirements), {"pandas", "openpyxl", "hermes-keenable-web", "hindsight-client>=0.10.1,<1", "hindsight-embed>=0.10.1,<1"})

    def test_image_has_font_and_runs_dependency_smoke_before_publication(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("fonts-wqy-zenhei", dockerfile)
        self.assertIn("verify_image_dependencies.py", dockerfile)
        self.assertNotIn("RUN uv pip install", dockerfile)
        self.assertIn("install_image_dependencies.py", dockerfile)
        self.assertNotIn("shellcheck-v0.10.0", dockerfile)
        self.assertIn("s6-setuidgid hermes", dockerfile)
        self.assertIn("cd / &&", dockerfile)

    def test_pm_replacement_reassembles_commands_and_readable_facts(self):
        adapter = self.load_adapter()
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            environment = source / ".venv"
            environment.mkdir()
            (environment / "old-package.txt").write_text("old")
            facts = source / "facts.json"
            facts.write_text("{}")
            facts.chmod(0o600)
            calls = []

            def run(command, **kwargs):
                calls.append(command)
                self.assertEqual(kwargs, {"cwd": source, "check": True})
                if len(calls) == 1:
                    self.assertFalse(environment.exists(), "PM must get a fresh destination")
                    (environment / "bin").mkdir(parents=True)
                    (environment / ".lock").write_text("build lock")

            with patch("subprocess.run", side_effect=run):
                adapter.rebuild_pm_environment(source, ["all"], facts)
            self.assertEqual(calls[1], [str(environment / "bin/python"), "-m", "docker.build_agent"])
            self.assertEqual(facts.stat().st_mode & 0o777, 0o644)
            self.assertFalse((environment / ".lock").exists())

    def test_legacy_silk_requirement_comes_from_upstream_lazy_allowlist(self):
        adapter = self.load_adapter()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "pyproject.toml").write_text('[project.optional-dependencies]\nfeishu=["lark-oapi==1.6.8"]\nedge-tts=["edge-tts==7.2.7"]\n')
            (root / "tools").mkdir()
            (root / "tools/lazy_deps.py").write_text('LAZY_DEPS: dict = {"stt.silk": ("pilk==0.2.4",)}\n')
            selected = adapter.feature_requirements(root)
            self.assertEqual(selected["silk"], ["pilk==0.2.4"])
            self.assertEqual(selected["feishu"], ["lark-oapi==1.6.8"])


if __name__ == "__main__":
    unittest.main()

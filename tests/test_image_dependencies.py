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

    def load_smoke(self):
        import sys
        with patch.dict(sys.modules, {"install_image_dependencies": self.load_adapter()}):
            spec = importlib.util.spec_from_file_location("image_smoke", ROOT / "scripts/verify_image_dependencies.py")
            assert spec is not None and spec.loader is not None
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        return module

    def test_rebuild_stages_pnpm_through_upstream_pm_before_readable_facts(self):
        import subprocess
        adapter = self.load_adapter()
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            facts = source / "facts.json"
            facts.write_text("{}")
            facts.chmod(0o600)
            def stage(command, **kwargs):
                if any("prepare_tools(" in token for token in command):
                    self.assertEqual(facts.stat().st_mode & 0o777, 0o600)
            with patch("subprocess.run", side_effect=stage) as run:
                adapter.rebuild_pm_environment(source, ["all"], facts)
            installs = [call for call in run.call_args_list
                        if any("prepare_tools(" in token for token in call.args[0])]
            self.assertEqual(len(installs), 1, "Locked tools must be prepared into the image-owned store")
            self.assertEqual(installs[0].args[0][0], str(source / ".venv/bin/python"))
            self.assertEqual(installs[0].args[0][-1], str(source / "tools"))
            self.assertEqual(installs[0].kwargs, {"cwd": source, "check": True})
            self.assertEqual(facts.stat().st_mode & 0o777, 0o644)
            with patch("subprocess.run", side_effect=[None, None, subprocess.CalledProcessError(1, "pnpm")]):
                with self.assertRaises(subprocess.CalledProcessError):
                    adapter.rebuild_pm_environment(source, ["all"], facts)

    def test_nonroot_pnpm_smoke_executes_locked_entry_and_rejects_wrong_version(self):
        import sys
        import types
        smoke = self.load_smoke()
        package = types.SimpleNamespace(binary=Path("/store/pnpm/pnpm"), version="12.15.0")
        pm = types.ModuleType("pm")
        setattr(pm, "installed_package", lambda name: package)
        with patch.dict(sys.modules, {"pm": pm}), patch.object(smoke.subprocess, "run") as run:
            run.return_value.stdout = "12.15.0\n"
            smoke.verify_pm_runtime_tools()
            run.assert_called_once_with(["/store/pnpm/pnpm", "--version"], check=True,
                                        capture_output=True, text=True, timeout=30, cwd="/")
            run.return_value.stdout = "0.0.0\n"
            with self.assertRaisesRegex(RuntimeError, "version"):
                smoke.verify_pm_runtime_tools()
        setattr(pm, "installed_package", lambda name: None)
        with patch.dict(sys.modules, {"pm": pm}), self.assertRaisesRegex(RuntimeError, "pnpm"):
            smoke.verify_pm_runtime_tools()

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

    def test_image_resolution_intersects_upstream_python_scope_with_linux_amd64(self):
        adapter = self.load_adapter()
        original = '''[project]
requires-python = ">=3.11,<3.15"
[project.optional-dependencies]
stt-whisper = ["faster-whisper==1.2.1"]
[tool.uv]
environments = ["python_version >= '3.14'"]
override-dependencies = ["Pillow==13.0.0"]
exclude-newer = "3 days"
[tool.other]
environments = ["unrelated"]
'''
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp) / "pyproject.toml"
            project.write_text(original)
            adapter.constrain_image_resolution(project)
            result = tomllib.loads(project.read_text())
        before = tomllib.loads(original)
        self.assertEqual(result["tool"]["uv"].pop("environments"), [
            "(python_version >= '3.14') and (sys_platform == 'linux' and platform_machine == 'x86_64')"
        ])
        before["tool"]["uv"].pop("environments")
        self.assertEqual(result, before, "Only the resolver target may change; no pins/features may be dropped")

    def test_resolution_scope_handles_missing_and_multiline_uv_settings(self):
        adapter = self.load_adapter()
        target = "sys_platform == 'linux' and platform_machine == 'x86_64'"
        for original, expected in [
            ('[project]\nname="hermes-agent"\n', [target]),
            ('[tool.uv]\nexclude-newer="3 days"\n', [target]),
            ('[tool.uv]\nenvironments=[]\n', [target]),
            ('[tool.uv]\nenvironments=[\n "python_version >= \'3.14\'",\n'
             ' "python_version == \'3.13\' or python_version == \'3.12\'",\n]\n',
             [f"(python_version >= '3.14') and ({target})",
              f"(python_version == '3.13' or python_version == '3.12') and ({target})"]),
        ]:
            with self.subTest(original=original), tempfile.TemporaryDirectory() as temp:
                project = Path(temp) / "pyproject.toml"
                project.write_text(original)
                adapter.constrain_image_resolution(project)
                self.assertEqual(tomllib.loads(project.read_text())["tool"]["uv"]["environments"], expected)

    def test_pm_cli_constrains_resolution_before_rebuilding(self):
        import sys
        import types

        adapter = self.load_adapter()
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp)
            (source / "pm").mkdir()
            (source / "pm/build_env.py").write_text("")
            facts = source / "facts.json"
            facts.write_text('{"packages":{"venv":{"extras":["all","matrix","documents"]}}}')
            (source / "pyproject.toml").write_text(
                '[project.optional-dependencies]\nfeishu=[]\nedge-tts=[]\nsilk=[]\n'
                'documents=["openpyxl==3.1.5"]\n'
                '[tool.uv]\nenvironments=["python_version >= \'3.14\'"]\n')
            requirements = source / "requirements.txt"
            requirements.write_text("pandas\n")
            pm_paths = types.ModuleType("pm.paths")
            setattr(pm_paths, "facts_path", lambda: facts)

            def rebuild(actual_source, baseline, actual_facts):
                self.assertEqual((actual_source, baseline, actual_facts), (source, ["all", "matrix", "documents"], facts))
                data = tomllib.loads((source / "pyproject.toml").read_text())
                self.assertIn("sys_platform == 'linux'", data["tool"]["uv"]["environments"][0])
                self.assertEqual(data["project"]["optional-dependencies"]["image-custom"], ["pandas"])

            with patch.dict(sys.modules, {"pm.paths": pm_paths}), \
                    patch("sys.argv", [str(SCRIPT), "--source", str(source), "--requirements", str(requirements)]), \
                    patch.object(adapter, "rebuild_pm_environment", side_effect=rebuild) as build:
                self.assertEqual(adapter.main(), 0)
                build.assert_called_once()

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
        self.assertEqual(extras, {"all", "matrix", "otlp", "feishu", "edge-tts", "silk", "documents", "image-custom"})

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

    def test_build_selects_release_owned_documents_even_without_a_baseline_selection(self):
        adapter = self.load_adapter()
        command = adapter.pm_build_command(Path("/image/hermes"), ["all"])
        extras = {command[i + 1] for i, value in enumerate(command) if value == "--extra"}
        self.assertIn("documents", extras, "XLSX must use the current release's documents capability")

    def test_custom_packages_are_unpinned_except_plugin_api_bounds(self):
        manifest = ROOT / "requirements-custom.txt"
        self.assertTrue(manifest.is_file(), "Missing explicit custom dependency manifest")
        requirements = [line.strip() for line in manifest.read_text().splitlines() if line.strip() and not line.startswith("#")]
        self.assertEqual(set(requirements), {"pandas", "hermes-keenable-web", "hindsight-client>=0.10.1,<1", "hindsight-embed>=0.10.1,<1"})

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

    def test_missing_feature_is_rejected_instead_of_reading_old_lazy_allowlist(self):
        adapter = self.load_adapter()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "pyproject.toml").write_text('[project.optional-dependencies]\nfeishu=["lark-oapi==1.6.8"]\nedge-tts=["edge-tts==7.2.7"]\n')
            (root / "tools").mkdir()
            (root / "tools/lazy_deps.py").write_text('LAZY_DEPS: dict = {"stt.silk": ("pilk==0.2.4",)}\n')
            with self.assertRaisesRegex(ValueError, "feature declarations"):
                adapter.feature_requirements(root)

    def test_non_pm_base_is_rejected_without_invoking_legacy_installer(self):
        adapter = self.load_adapter()
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            (source / "pyproject.toml").write_text(
                '[project.optional-dependencies]\nfeishu=[]\nedge-tts=[]\nsilk=[]\n')
            requirements = source / "requirements.txt"
            requirements.write_text("pandas\n")
            with patch("sys.argv", [str(SCRIPT), "--source", str(source),
                                    "--requirements", str(requirements)]), \
                    patch("shutil.which", return_value="/legacy/uv"), \
                    patch("subprocess.run") as run:
                with self.assertRaisesRegex(ValueError, "supported PM"):
                    adapter.main()
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()

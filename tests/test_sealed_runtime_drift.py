"""Exercise upstream PM code in memory; never modify the installed source tree."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(os.environ.get("HERMES_SOURCE_ROOT", "/opt/hermes"))
PATCH = ROOT / "patches/apply_sealed_runtime_drift.py"
sys.path.insert(0, str(SOURCE))


class SealedRuntimeDriftTests(unittest.TestCase):
    def setUp(self):
        from pm.lock import Facts
        from pm.packages import Venv
        import pm.environments
        import pm.workspace
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.facts = self.root / "facts.json"
        self.runtime = self.root / "runtime-facts.json"
        (self.root / ".venv").mkdir()
        (self.root / ".venv/pyvenv.cfg").write_text("home = /python\n")
        (self.root / "uv.lock").write_text("version = 1\n")
        (self.root / "pyproject.toml").write_text('[project.optional-dependencies]\nall=[]\n')
        (self.root / "install-stamp.json").write_text(json.dumps({
            "distribution": "docker", "updateMechanism": "external"}))
        self.plugin = self.root / "plugins/example"
        self.plugin.mkdir(parents=True)
        (self.plugin / "pyproject.toml").write_text(
            '[project]\nname="example-plugin"\nversion="1.0"\ndependencies=["httpx"]\n')
        source = (SOURCE / "pm/install.py").read_text()
        if PATCH.is_file() and not os.environ.get("HERMES_TEST_USE_SOURCE_AS_IS"):
            spec = importlib.util.spec_from_file_location("sealed_drift_patch", PATCH)
            assert spec is not None and spec.loader is not None
            adapter = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(adapter)
            source = adapter.patch_source(source)
        self.engine = types.ModuleType("pm._sealed_drift_test")
        registered = patch.dict(sys.modules, {self.engine.__name__: self.engine})
        registered.start()
        self.addCleanup(registered.stop)
        exec(compile(source, str(SOURCE / "pm/install.py"), "exec"), self.engine.__dict__)
        self.package = Venv(self.root)
        self.extras = ["all"]
        self.stamp = self.package.expected_stamp(self.extras, plugin_dirs=[])
        Facts(self.facts).record_state("venv", self.stamp, self.extras)
        for target, value in (
            ("pm.paths.repo_root", lambda: self.root),
            ("pm.paths.facts_path", lambda: self.facts),
            ("pm.paths.runtime_facts_path", lambda: self.runtime),
            ("pm.environments.runtime_facts_path", lambda root: self.runtime),
            ("pm.environments.selected_venv", lambda root: self.root / ".venv"),
            ("pm.workspace.enabled_member_dirs", lambda: [self.plugin]),
        ):
            mock = patch(target, value)
            mock.start()
            self.addCleanup(mock.stop)
        for name, value in (
            ("_lockfile", lambda: types.SimpleNamespace(names=lambda: [])),
            ("_facts", lambda: Facts(self.facts, strict=True)),
            ("get_package", lambda name: self.package),
            ("_store_path_dirs", lambda: []),
        ):
            mock = patch.object(self.engine, name, value)
            mock.start()
            self.addCleanup(mock.stop)

    def verdict(self):
        import pm
        from hermes_cli.venv_sync import check_runtime
        with patch.object(pm, "activate", self.engine.activate):
            return check_runtime(self.root)

    def test_sealed_base_does_not_compare_profile_members_to_baked_stamp(self):
        from hermes_cli.venv_sync import sync
        self.assertEqual(sync(self.root, check=True), {"state": "sealed", "ok": True})
        self.assertIsNone(self.verdict())
        (self.plugin / "pyproject.toml").write_text('[project]\nname="changed"\nversion="2"\n')
        self.assertIsNone(self.verdict())

    def test_explicit_currency_probe_still_requires_plugin_union(self):
        self.assertFalse(self.engine.venv_is_current())

    def test_baked_lock_drift_still_warns(self):
        (self.root / "uv.lock").write_text("version = 2\n")
        self.assertIn("venv: out of sync", self.verdict())

    def test_missing_environment_still_warns(self):
        (self.root / ".venv/pyvenv.cfg").unlink()
        self.assertIn("venv: out of sync", self.verdict())

    def test_baked_selection_drift_still_warns(self):
        data = json.loads(self.facts.read_text())
        data["packages"]["venv"]["extras"] = []
        self.facts.write_text(json.dumps(data))
        self.assertIn("venv: out of sync", self.verdict())

    def test_invalid_sealed_stamp_is_not_hidden(self):
        (self.root / "install-stamp.json").write_text('{"updateMechanism":"invalid"}')
        self.assertIsNotNone(self.verdict())

    def test_probe_does_not_write_dependency_inputs(self):
        def snapshot():
            return {str(p.relative_to(self.root)): p.read_bytes()
                    for p in self.root.rglob("*") if p.is_file()}
        before = snapshot()
        self.verdict()
        self.assertEqual(before, snapshot())

    def test_checkout_keeps_plugin_union_check(self):
        (self.root / ".git").mkdir()
        self.assertIn("venv", self.engine.drift())

    def test_runtime_selection_keeps_plugin_union_and_detects_edits(self):
        from pm.lock import Facts
        stamp = self.package.expected_stamp(self.extras, plugin_dirs=[self.plugin])
        Facts(self.runtime).record_state("venv", stamp, self.extras,
                                        environment=self.root / ".venv")
        self.assertIsNone(self.verdict())
        (self.plugin / "code.py").write_text("changed = True\n")
        self.assertIn("venv: out of sync", self.verdict())

    def test_invalid_runtime_selection_is_not_hidden(self):
        self.runtime.write_text("not json")
        self.assertIsNotNone(self.verdict())

    def test_tool_drift_is_not_hidden(self):
        tool = types.SimpleNamespace(optional=False, internal=False,
                                     missing_reason=lambda target: None)
        with patch.object(self.engine, "_lockfile", return_value=types.SimpleNamespace(names=lambda: ["python"])), \
             patch.object(self.engine, "get_package", side_effect=lambda name: self.package if name == "venv" else tool), \
             patch.object(self.engine, "_installed_location", return_value=None):
            self.assertIn("python: not installed or outdated", self.verdict())


class PatchSafetyTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("sealed_drift_patch", PATCH)
        assert spec is not None and spec.loader is not None
        self.adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.adapter)

    def test_known_source_is_idempotent_and_only_changes_drift(self):
        source = (SOURCE / "pm/install.py").read_text()
        updated = self.adapter.patch_source(source)
        self.assertEqual(updated, self.adapter.patch_source(updated))
        self.assertEqual(source[:source.index("def drift(")], updated[:updated.index("def drift(")])
        self.assertEqual(source[source.index("\ndef check("):], updated[updated.index("\ndef check("):])

    def test_unknown_upstream_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "Unknown PM drift"):
            self.adapter.patch_source("def drift(): pass\n")

    def test_cli_patches_only_temporary_target(self):
        import subprocess
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "pm").mkdir()
            target = root / "pm/install.py"
            target.write_text((SOURCE / "pm/install.py").read_text())
            for _ in range(2):
                result = subprocess.run([sys.executable, str(PATCH), str(root)],
                                        capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(target.read_text(), self.adapter.patch_source(target.read_text()))


if __name__ == "__main__":
    unittest.main(verbosity=2)

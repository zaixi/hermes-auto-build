"""Test behavior-first patch orchestration without needing a Hermes install."""
import importlib.util
import json
import os
import contextlib
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
GATE = ROOT / "scripts/ensure_sealed_runtime_drift.py"


class SealedDriftGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "source"
        (self.source / "pm").mkdir(parents=True)
        (self.source / "pm/build_env.py").touch()
        self.target = self.source / "pm/install.py"
        self.target.write_text("# different but behaviorally correct upstream implementation\n")
        self.probe = Path(self.temp.name) / "probe.py"
        self.statuses = self.source / "statuses.json"
        self.events = self.source / "events.json"
        self.probe.write_text('''import json, os, pathlib, sys
assert sys.argv[1:] == ["--probe"]
source = pathlib.Path(os.environ["HERMES_SOURCE_ROOT"])
assert os.environ["HERMES_TEST_USE_SOURCE_AS_IS"] == "1"
assert os.environ["PYTHONDONTWRITEBYTECODE"] == "1"
p = source / "statuses.json"
statuses = json.loads(p.read_text())
status = statuses.pop(0)
p.write_text(json.dumps(statuses))
events = source / "events.json"
seen = json.loads(events.read_text()) if events.exists() else []
seen.append((source / "pm/install.py").read_text())
events.write_text(json.dumps(seen))
raise SystemExit(status)
''')

    def load_gate(self):
        self.assertTrue(GATE.is_file(), "Missing behavior-first build gate")
        spec = importlib.util.spec_from_file_location("sealed_drift_gate", GATE)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def known_source(self):
        spec = importlib.util.spec_from_file_location(
            "drift_adapter", ROOT / "patches/apply_sealed_runtime_drift.py")
        assert spec is not None and spec.loader is not None
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        source = ("from pm.plugin_inputs import Members\n\ndef drift():\n"
                  "    problems = {}\n    if True:\n" + adapter.OLD +
                  "    return problems\n\ndef check():\n    pass\n")
        self.target.write_text(source)
        return source, adapter.patch_source(source)

    def run_gate(self, statuses):
        self.statuses.write_text(json.dumps(statuses))
        return self.load_gate().ensure(self.source, tests=self.probe)

    def test_fixed_upstream_skips_patch_even_with_unrecognized_source_text(self):
        original = self.target.read_bytes()
        self.assertEqual(self.run_gate([0]), "upstream")
        self.assertEqual(self.target.read_bytes(), original)
        self.assertEqual(len(json.loads(self.events.read_text())), 1)


    def test_known_bug_is_patched_then_probed_again(self):
        original, updated = self.known_source()
        self.assertEqual(self.run_gate([1, 0]), "patched")
        self.assertEqual(self.target.read_text(), updated)
        self.assertEqual(json.loads(self.events.read_text()), [original, updated])

    def test_unknown_failing_upstream_is_not_modified(self):
        original = self.target.read_bytes()
        with self.assertRaisesRegex(ValueError, "Unknown PM drift"):
            self.run_gate([1])
        self.assertEqual(self.target.read_bytes(), original)

    def test_probe_errors_or_signals_do_not_authorize_a_patch(self):
        original, _ = self.known_source()
        for code in (2, -9, 99):
            with self.subTest(code=code):
                with self.assertRaisesRegex(RuntimeError, "probe"):
                    self.run_gate([code])
                self.assertEqual(self.target.read_text(), original)

    def test_failed_post_patch_probe_restores_source(self):
        original, _ = self.known_source()
        for code in (1, 2):
            with self.subTest(code=code):
                with self.assertRaisesRegex(RuntimeError, "after patch"):
                    self.run_gate([1, code])
                self.assertEqual(self.target.read_text(), original)

    def test_timeout_after_patch_restores_source(self):
        original, _ = self.known_source()
        gate = self.load_gate()
        with patch.object(gate, "run_probe", side_effect=[1, subprocess.TimeoutExpired("probe", 120)]):
            with self.assertRaises(subprocess.TimeoutExpired):
                gate.ensure(self.source, tests=self.probe)
        self.assertEqual(self.target.read_text(), original)

    def test_legacy_non_pm_source_skips_without_a_probe(self):
        self.target.unlink()
        (self.source / "pm/build_env.py").unlink()
        self.assertEqual(self.run_gate([]), "legacy")
        self.assertFalse(self.events.exists())

    def test_missing_pm_engine_fails_without_a_probe(self):
        self.target.unlink()
        with self.assertRaisesRegex(ValueError, "install engine is missing"):
            self.run_gate([])
        self.assertFalse(self.events.exists())

    def test_dockerfile_uses_behavior_gate_not_the_patch_cli_first(self):
        dockerfile = (ROOT / "Dockerfile").read_text()
        self.assertIn("COPY scripts/ensure_sealed_runtime_drift.py", dockerfile)
        self.assertIn("python /tmp/image-regression/scripts/ensure_sealed_runtime_drift.py /opt/hermes", dockerfile)
        self.assertNotIn("python /tmp/image-regression/patches/apply_sealed_runtime_drift.py", dockerfile)


class ProbeProtocolTests(unittest.TestCase):
    def test_probe_rejects_errors_skips_expected_failures_and_empty_suites(self):
        spec = importlib.util.spec_from_file_location(
            "sealed_drift_behavior", ROOT / "tests/test_sealed_runtime_drift.py")
        assert spec is not None and spec.loader is not None
        behavior = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(behavior)
        for outcome, expected in (("pass", 0), ("fail", 1), ("error", 2),
                                  ("skip", 2), ("expected_failure", 2), ("empty", 2)):
            with self.subTest(outcome=outcome):
                class Case(unittest.TestCase):
                    def test_contract(self):
                        if outcome in ("fail", "expected_failure"):
                            self.fail("deliberate test fixture failure")
                        if outcome == "error":
                            raise RuntimeError("deliberate test fixture error")
                        if outcome == "skip":
                            self.skipTest("deliberate test fixture skip")
                if outcome == "expected_failure":
                    Case.test_contract = unittest.expectedFailure(Case.test_contract)
                if outcome == "empty":
                    class EmptyCase(unittest.TestCase):
                        pass
                    selected = EmptyCase
                else:
                    selected = Case
                with patch.object(behavior, "SealedRuntimeDriftTests", selected), \
                     contextlib.redirect_stderr(io.StringIO()):
                    self.assertEqual(behavior.probe_main(), expected)


SOURCE = Path(os.environ.get("HERMES_SOURCE_ROOT", "/opt/hermes"))


@unittest.skipUnless((SOURCE / "pm/install.py").is_file(), "Hermes source is needed for integration")
class ActualUpstreamGateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.source = Path(self.temp.name) / "source"
        self.source.mkdir()
        # Share read-only source/dependencies, but never symlink the rewrite target.
        for entry in SOURCE.iterdir():
            if entry.name != "pm":
                (self.source / entry.name).symlink_to(entry.resolve(), target_is_directory=entry.is_dir())
        (self.source / "pm").mkdir()
        for entry in (SOURCE / "pm").iterdir():
            if entry.name != "install.py":
                (self.source / "pm" / entry.name).symlink_to(entry.resolve(), target_is_directory=entry.is_dir())
        self.target = self.source / "pm/install.py"
        self.original = (SOURCE / "pm/install.py").read_bytes()
        self.target.write_bytes(self.original)
        spec = importlib.util.spec_from_file_location(
            "integration_drift_adapter", ROOT / "patches/apply_sealed_runtime_drift.py")
        assert spec is not None and spec.loader is not None
        self.adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.adapter)
        unchanged = self.original
        self.original = self.original.replace(self.adapter.NEW.encode(), self.adapter.OLD.encode())
        self.target.write_bytes(self.original)
        def assert_upstream_unchanged():
            self.assertEqual((SOURCE / "pm/install.py").read_bytes(), unchanged)
        self.addCleanup(assert_upstream_unchanged)

    def run_gate(self):
        return subprocess.run([sys.executable, str(GATE), str(self.source)],
                              env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
                              cwd="/", capture_output=True, text=True, timeout=60)

    def test_actual_bug_is_fixed_and_second_run_skips(self):
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("Applied audited sealed PM compatibility patch", result.stdout)
        self.assertEqual(self.target.read_text(), self.adapter.patch_source(self.original.decode()))
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("compatibility patch skipped", result.stdout)

    def test_different_fixed_source_passes_without_rewrite(self):
        fixed = self.adapter.patch_source(self.original.decode()).replace(
            "venv_is_current(**inputs)", "venv_is_current( **inputs )")
        with self.assertRaises(ValueError):
            self.adapter.patch_source(fixed)
        self.target.write_text(fixed)
        result = self.run_gate()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("compatibility patch skipped", result.stdout)
        self.assertEqual(self.target.read_text(), fixed)

    def test_unknown_broken_source_fails_without_rewrite(self):
        broken = self.original.decode().replace("if not venv_is_current():", "if not venv_is_current( ):")
        self.target.write_text(broken)
        result = self.run_gate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Unknown PM drift", result.stderr)
        self.assertEqual(self.target.read_text(), broken)

    def test_unknown_api_errors_block_before_patch(self):
        broken = self.original.decode().replace("def venv_is_current(", "def renamed_currency_probe(")
        self.target.write_text(broken)
        result = self.run_gate()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("could not run completely", result.stderr)
        self.assertEqual(self.target.read_text(), broken)

    def test_direct_probe_never_auto_applies_the_adapter(self):
        env = dict(os.environ, HERMES_SOURCE_ROOT=str(self.source), PYTHONDONTWRITEBYTECODE="1")
        env.pop("HERMES_TEST_USE_SOURCE_AS_IS", None)
        result = subprocess.run([sys.executable, str(ROOT / "tests/test_sealed_runtime_drift.py"), "--probe"],
                                env=env, cwd="/", capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(self.target.read_bytes(), self.original)


if __name__ == "__main__":
    unittest.main(verbosity=2)

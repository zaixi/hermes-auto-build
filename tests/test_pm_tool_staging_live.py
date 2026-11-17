"""Real upstream PM tool-staging regression, opt-in locally and mandatory in CI.

Uses real locked tools and downloads; only the expensive application environment
build/assembler are intercepted. The tool-install command runs unmodified in a
copied sealed payload, then a fresh process/home must find its baked entry.
"""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SOURCE = os.environ.get("HERMES_TOOL_SOURCE")
PM_PYTHON = os.environ.get("HERMES_TOOL_PM_PYTHON")
SEED = os.environ.get("HERMES_TOOL_SEED_STORE")
ADAPTER = Path(os.environ.get("HERMES_IMAGE_ADAPTER", ROOT / "scripts/install_image_dependencies.py"))


@unittest.skipUnless(SOURCE and PM_PYTHON and SEED, "explicit real PM source, interpreter and seed store required")
class RealToolStagingTests(unittest.TestCase):
    def test_baked_tool_survives_fresh_home_and_missing_entry_is_rejected(self):
        assert SOURCE is not None and PM_PYTHON is not None and SEED is not None
        original_run = subprocess.run
        spec = importlib.util.spec_from_file_location("live_image_adapter", ADAPTER)
        assert spec is not None and spec.loader is not None
        adapter = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(adapter)
        with tempfile.TemporaryDirectory(prefix="hermes-tool-staging-") as directory:
            root = Path(directory)
            payload = root / "payload"
            payload.mkdir()
            shutil.copytree(Path(SOURCE) / "pm", payload / "pm",
                            ignore=shutil.ignore_patterns("__pycache__"))
            # This is the same stdlib-only bootstrap surface the official
            # Dockerfile copies before application dependencies/frontends exist.
            (payload / "hermes_cli").mkdir()
            for name in ("__init__.py", "runtime_state.py"):
                shutil.copy2(Path(SOURCE) / "hermes_cli" / name, payload / "hermes_cli" / name)
            shutil.copy2(Path(SOURCE) / "hermes_constants.py", payload / "hermes_constants.py")
            (payload / "manifest.json").write_text(json.dumps({"repo": ".", "store": "tools"}))
            builder, fresh = root / "builder-home", root / "fresh-home"
            builder.mkdir()
            fresh.mkdir()
            env = dict(os.environ, HOME=str(builder), HERMES_HOME=str(builder),
                       HERMES_RUNTIME_DIR=str(payload / "tools"), PYTHONDONTWRITEBYTECODE="1")
            for name in ("HERMES_INSTALL_ROOT", "HERMES_PROFILE", "PYTHONPATH"):
                env.pop(name, None)
            # Seed only pnpm's real node dependency, never pnpm itself. The exact
            # locked artifacts and tree hashes are verified by upstream stage_tools.
            seed = (
                "from pathlib import Path; import sys; "
                "sys.path.insert(0, sys.argv[1]); "
                "from pm import stage_tools; from pm.store import current_target; "
                "stage_tools(['node'], source_store=Path(sys.argv[2]), "
                "out=Path(sys.argv[1]) / 'tools', target=current_target())"
            )
            original_run([PM_PYTHON, "-c", seed, str(payload), SEED], env=env,
                         cwd="/", check=True, timeout=120)
            facts = payload / "tools/facts.json"
            node_before = json.loads(facts.read_text())["packages"]["node"]
            environment = payload / ".venv"
            environment.symlink_to(Path(PM_PYTHON).parent.parent, target_is_directory=True)

            def run(command, **kwargs):
                if "-m" in command and "pm.build_env" in command:
                    self.assertFalse(environment.exists(), "Application builder requires a fresh destination")
                    environment.symlink_to(Path(PM_PYTHON).parent.parent, target_is_directory=True)
                    return subprocess.CompletedProcess(command, 0)
                if "-m" in command and "docker.build_agent" in command:
                    return subprocess.CompletedProcess(command, 0)
                return original_run(command, **kwargs, timeout=180)

            with patch.dict(os.environ, env, clear=True), patch("subprocess.run", side_effect=run):
                adapter.rebuild_pm_environment(payload, ["all"], facts)
            # This is a build-owned store update, not replacement of other pins.
            self.assertEqual(json.loads(facts.read_text())["packages"]["node"], node_before)
            # Remove access to the builder data root, not just its environment
            # variable. A hidden runtime installation must not satisfy the probe.
            builder.rename(root / "retired-builder-home")
            fresh_env = dict(env, HOME=str(fresh), HERMES_HOME=str(fresh))
            probe = (
                "import json,sys,subprocess; sys.path.insert(0,sys.argv[1]); "
                "from pathlib import Path; from pm import installed_package; "
                "package=installed_package('pnpm'); "
                "assert package is not None, 'pnpm disappeared under a fresh HOME'; "
                "assert package.path.is_relative_to(Path(sys.argv[1])/'tools'), 'pnpm is not baked'; "
                "version=subprocess.check_output([str(package.binary),'--version'],text=True,cwd='/').strip(); "
                "assert version==package.version; "
                "print(json.dumps({'entry':str(package.path),'version':version}))"
            )
            result = original_run([PM_PYTHON, "-c", probe, str(payload)], env=fresh_env,
                                  cwd="/", capture_output=True, text=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stderr)
            package = json.loads(result.stdout)
            entry = Path(package["entry"])
            print(f"Real fresh-home locked tool OK: {package['version']}", flush=True)
            hidden = entry.with_name(entry.name + ".negative-control")
            entry.rename(hidden)
            try:
                negative = (
                    "import sys; sys.path.insert(0,sys.argv[1]); "
                    "from pm import installed_package; "
                    "assert installed_package('pnpm') is None, 'missing entry accepted'"
                )
                original_run([PM_PYTHON, "-c", negative, str(payload)], env=fresh_env,
                             cwd="/", check=True, timeout=30)
            finally:
                hidden.rename(entry)
            print("Real missing-entry negative control OK", flush=True)


if __name__ == "__main__":
    unittest.main(verbosity=2)

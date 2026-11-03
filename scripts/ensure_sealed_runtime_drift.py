#!/usr/bin/env python3
"""Build-only behavior gate for the sealed PM diagnostic compatibility fix."""
import argparse
import importlib.util
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT / "tests/test_sealed_runtime_drift.py"


def run_probe(source: Path, tests: Path) -> int:
    env = dict(os.environ, HERMES_SOURCE_ROOT=str(source),
               HERMES_TEST_USE_SOURCE_AS_IS="1", PYTHONDONTWRITEBYTECODE="1")
    return subprocess.run(
        [sys.executable, str(tests), "--probe"], env=env, cwd="/",
        timeout=120, check=False,
    ).returncode


def ensure(source: Path, *, tests: Path = TESTS) -> str:
    source = source.resolve()
    if not source.is_dir():
        raise ValueError(f"Hermes source directory is missing: {source}")
    target = source / "pm/install.py"
    if not target.is_file():
        if target.exists() or (source / "pm/build_env.py").exists():
            raise ValueError("PM build API exists but install engine is missing")
        print("Legacy non-PM image: no sealed PM drift patch needed", flush=True)
        return "legacy"

    tests = tests.resolve()
    print("Checking upstream sealed PM behavior before considering a patch", flush=True)
    status = run_probe(source, tests)
    if status == 0:
        print("Upstream sealed PM behavior OK; compatibility patch skipped", flush=True)
        return "upstream"
    if status != 1:
        raise RuntimeError(f"Sealed PM behavior probe could not run completely (exit {status}); refusing to patch")

    # Only an actual assertion failure can request the existing audited adapter.
    # Broken imports/APIs, skipped tests and signals must not authorize a rewrite.
    spec = importlib.util.spec_from_file_location(
        "sealed_drift_patch", ROOT / "patches/apply_sealed_runtime_drift.py")
    if spec is None or spec.loader is None:
        raise RuntimeError("Cannot load the audited sealed PM patch adapter")
    adapter = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(adapter)
    original = target.read_bytes()
    updated = adapter.patch_source(original.decode("utf-8")).encode("utf-8")
    if updated == original:
        raise RuntimeError("Behavior fails although the audited patch is already present")

    try:
        target.write_bytes(updated)
        if run_probe(source, tests) != 0:
            raise RuntimeError("Sealed PM behavior probe failed after patch; refusing this image")
    except BaseException:
        # Failed builds and interrupted probes must not leave a partial repair.
        target.write_bytes(original)
        raise
    print("Applied audited sealed PM compatibility patch; behavior regression OK", flush=True)
    return "patched"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="build-stage Hermes source root")
    args = parser.parse_args()
    try:
        ensure(args.source)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"Sealed PM compatibility gate failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

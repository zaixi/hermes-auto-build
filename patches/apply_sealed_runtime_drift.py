#!/usr/bin/env python3
"""Build-only compatibility fix for sealed PM base-vs-runtime diagnostics.

Do not change venv_is_current or sync/admission: only passive drift diagnostics
compare an unextended sealed payload with the plugin-free selection it shipped.
This is a downstream fix, not an upstream release backport.
"""
from pathlib import Path
import argparse

OLD = '''        try:
            if not venv_is_current():
                problems["venv"] = "out of sync with uv.lock"
        except (OSError, RuntimeError, ValueError) as exc:
            problems["venv"] = str(exc)
'''

NEW = '''        try:
            # Sealed base selections are built with plugin_dirs=[]; profile plugins
            # are not build inputs. Only a published runtime selection owns their
            # union. Keep currency probes and admission/sync strict and unchanged.
            from hermes_cli.venv_sync import _is_sealed

            runtime_selection = Facts(paths.runtime_facts_path(), strict=True).get("venv")
            base_only = runtime_selection is None and _is_sealed(paths.repo_root())
            inputs = {"plugins": Members([])} if base_only else {}
            if not venv_is_current(**inputs):
                problems["venv"] = "out of sync with uv.lock"
        except (OSError, RuntimeError, ValueError) as exc:
            problems["venv"] = str(exc)
'''


def patch_source(source: str) -> str:
    """Recognize only the audited drift block; upstream changes require review."""
    if source.count(NEW) == 1 and OLD not in source:
        return source
    if source.count(OLD) != 1 or NEW in source:
        raise ValueError("Unknown PM drift implementation; review upstream before building")
    start = source.index("def drift(")
    end = source.index("\ndef check(", start)
    block = source[start:end]
    if block.count(OLD) != 1 or "from pm.plugin_inputs import" not in source:
        raise ValueError("Expected audited PM drift and typed member inputs")
    result = source[:start] + block.replace(OLD, NEW, 1) + source[end:]
    compile(result, "pm/install.py", "exec")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="build-stage Hermes source root")
    args = parser.parse_args()
    target = args.source / "pm/install.py"
    if not target.exists():
        if (args.source / "pm/build_env.py").exists():
            raise ValueError("PM build API exists but install engine is missing")
        print("Legacy non-PM image: no sealed PM drift patch needed")
        return 0
    source = target.read_text(encoding="utf-8")
    updated = patch_source(source)
    if updated != source:
        target.write_text(updated, encoding="utf-8")
    print("Sealed PM base/runtime drift diagnostic fix ready")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

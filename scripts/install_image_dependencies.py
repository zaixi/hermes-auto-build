"""Assemble custom image dependencies without bypassing upstream PM ownership."""
from pathlib import Path
import json
import tomllib

CUSTOM_EXTRA = "image-custom"


def feature_requirements(source: Path) -> dict[str, list[str]]:
    """Use release-owned extras, with the old allowlist as a legacy fallback."""
    import ast

    data = tomllib.loads((source / "pyproject.toml").read_text())
    extras = data.get("project", {}).get("optional-dependencies", {})
    features = {"feishu": "platform.feishu", "edge-tts": "tts.edge", "silk": "stt.silk"}
    result = {extra: list(extras[extra]) for extra in features if extra in extras}
    missing = features.keys() - result.keys()
    if missing and not (source / "pm/build_env.py").is_file():
        tree = ast.parse((source / "tools/lazy_deps.py").read_text())
        for node in tree.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "LAZY_DEPS":
                if node.value is None:
                    continue
                allowlist = ast.literal_eval(node.value)
                for extra in missing:
                    if features[extra] in allowlist:
                        result[extra] = list(allowlist[features[extra]])
    if features.keys() - result.keys():
        raise ValueError(f"Missing upstream feature declarations: {sorted(features.keys() - result.keys())}")
    return result


def pm_build_command(source: Path, baseline: list[str]) -> list[str]:
    """Extend, rather than replace, the official image's selected capabilities."""
    extras = sorted(set(baseline) | {"feishu", "edge-tts", "silk", CUSTOM_EXTRA})
    command = [
        "python3", "-m", "pm.build_env", "--source", str(source),
        "--out", str(source / ".venv"), "--cache", str(source / "uv-cache"),
        "--python", "/usr/local/bin/python3", "--no-install-project",
        "--sealed", "--resolve", "--record-selection",
    ]
    for extra in extras:
        command.extend(["--extra", extra])
    return command


def recorded_selection(facts: Path) -> list[str] | None:
    """The base image's own sealed selection, or None when it predates it.

    Upstream records the shipped extras only from v0.21.7 (`pm.build_env
    --record-selection`); a v0.21.6-style image has a PM build API and no
    selection. Such a base cannot be extended without silently dropping the
    extras upstream built in, so it is refused rather than guessed.
    """
    data = json.loads(facts.read_text(encoding="utf-8"))
    extras = data.get("packages", {}).get("venv", {}).get("extras")
    if extras is None:
        return None
    if not isinstance(extras, list) or not extras or not all(isinstance(x, str) and x for x in extras):
        raise ValueError("Missing or invalid upstream dependency selection")
    return extras


def add_custom_extra(project: Path, requirements: list[str]) -> None:
    """Append a custom extra, leaving upstream declarations and comments intact."""
    text = project.read_text(encoding="utf-8")
    data = tomllib.loads(text)
    if CUSTOM_EXTRA in data.get("project", {}).get("optional-dependencies", {}):
        raise ValueError(f"{CUSTOM_EXTRA} is already declared; refusing an ambiguous build")
    values = ",\n".join(f"  {json.dumps(item)}" for item in requirements)
    # Insert an array into the existing table while preserving upstream comments.
    section = "[project.optional-dependencies]"
    if text.count(section) != 1:
        raise ValueError("Expected one upstream optional-dependencies table")
    updated = text.replace(section, f'{section}\n{CUSTOM_EXTRA} = [\n{values}\n]\n', 1)
    tomllib.loads(updated)
    project.write_text(updated, encoding="utf-8")


def rebuild_pm_environment(source: Path, baseline: list[str], facts: Path) -> None:
    """Replace the baked environment, then restore the official offline assembly."""
    import shutil
    import subprocess

    environment = source / ".venv"
    # This only runs in the Docker build layer; never against a running service.
    # Do not follow a generation symlink and delete its target.
    if environment.is_symlink():
        environment.unlink()
    elif environment.exists():
        shutil.rmtree(environment)
    command = pm_build_command(source, baseline)
    print("Building image dependencies:", command, flush=True)
    subprocess.run(command, cwd=source, check=True)
    subprocess.run([str(environment / "bin/python"), "-m", "docker.build_agent"],
                   cwd=source, check=True)
    facts.chmod(0o644)
    for lock in (environment / ".lock", source / "pm-runtime" / ".lock"):
        lock.unlink(missing_ok=True)


def main() -> int:
    import argparse
    import shutil
    import subprocess
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--requirements", required=True, type=Path)
    args = parser.parse_args()
    source = args.source.resolve()
    requirements = [line.strip() for line in args.requirements.read_text().splitlines()
                    if line.strip() and not line.lstrip().startswith("#")]
    project = source / "pyproject.toml"
    official = feature_requirements(source)

    if (source / "pm" / "build_env.py").is_file():
        # PM is stdlib-only at bootstrap. Never invoke the application venv's
        # interpreter while asking PM to atomically replace that same venv.
        sys.path.insert(0, str(source))
        from pm.paths import facts_path

        facts = facts_path()
        baseline = recorded_selection(facts)
        if baseline is None:
            raise ValueError(
                "Base image predates the sealed dependency selection this build extends "
                "(upstream pm.build_env --record-selection, first shipped in v0.21.7); "
                "refusing to rebuild an unrecorded environment"
            )
        add_custom_extra(project, requirements)
        rebuild_pm_environment(source, baseline, facts)
        return 0
    else:
        # Older release tags still use uv on PATH. Preserve gap-fill support;
        # do not install a second package manager into modern PM-owned images.
        uv = shutil.which("uv")
        if uv is None:
            raise ValueError("Neither upstream PM nor its legacy uv installer is available")
        selected = list(requirements)
        for specifications in official.values():
            selected.extend(specifications)
        command = [uv, "pip", "install", "--python", str(source / ".venv/bin/python"),
                   "--no-cache", *selected]
    print("Building image dependencies:", command, flush=True)
    subprocess.run(command, cwd=source, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

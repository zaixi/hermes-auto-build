"""Assemble custom image dependencies without bypassing upstream PM ownership."""
from pathlib import Path
import json
import tomllib

CUSTOM_EXTRA = "image-custom"
FEATURE_EXTRAS = ("feishu", "edge-tts", "silk", "documents")


def feature_requirements(source: Path) -> dict[str, list[str]]:
    """Read required capabilities from the supported release's public extras."""
    data = tomllib.loads((source / "pyproject.toml").read_text())
    extras = data.get("project", {}).get("optional-dependencies", {})
    missing = set(FEATURE_EXTRAS) - extras.keys()
    if missing:
        raise ValueError(f"Missing upstream feature declarations: {sorted(missing)}")
    return {extra: list(extras[extra]) for extra in FEATURE_EXTRAS}


def pm_build_command(source: Path, baseline: list[str]) -> list[str]:
    """Extend, rather than replace, the official image's selected capabilities."""
    extras = sorted(set(baseline) | set(FEATURE_EXTRAS) | {CUSTOM_EXTRA})
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


def constrain_image_resolution(project: Path) -> None:
    """Resolve this Linux amd64 image, not unsupported universal-lock targets.

    uv lock considers every extra, even ones not selected for installation.
    v0.22.5's Python-only scope includes emscripten, where faster-whisper's
    wheel-only closure cannot resolve. Intersect upstream's scope with our
    image target; retain its Python floor, overrides, pins and capabilities.
    """
    import re

    text = project.read_text(encoding="utf-8")
    data = tomllib.loads(text)
    uv = data.get("tool", {}).get("uv", {})
    target = "sys_platform == 'linux' and platform_machine == 'x86_64'"
    scopes = uv.get("environments") or []
    environments = [f"({scope}) and ({target})" for scope in scopes] or [target]
    assignment = f"environments = {json.dumps(environments)}"
    table = re.search(r"(?m)^\[tool\.uv\][ \t]*(?:#.*)?\n", text)
    if table is None:
        updated = text + f"\n[tool.uv]\n{assignment}\n"
    else:
        following = re.search(r"(?m)^\[", text[table.end():])
        end = table.end() + following.start() if following else len(text)
        body = text[table.end():end]
        if "environments" in uv:
            body, count = re.subn(r"(?m)^environments[ \t]*=[ \t]*\[[^\]]*\]",
                                  lambda _: assignment, body)
            if count != 1:
                raise ValueError("Cannot safely constrain upstream uv environments")
        else:
            body = assignment + "\n" + body
        updated = text[:table.end()] + body + text[end:]
    expected = data.setdefault("tool", {}).setdefault("uv", {})
    expected["environments"] = environments
    if tomllib.loads(updated) != data:
        raise ValueError("Resolver target edit changed unrelated upstream metadata")
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
    # The payload is sealed after assembly. Runtime ensure() intentionally
    # writes missing tools to HERMES_HOME/tools, which a fresh profile or data
    # volume cannot see. Use the official build operation to publish the full
    # locked tool closure and facts in the immutable image-owned store.
    subprocess.run([
        str(environment / "bin/python"), "-c",
        "from pathlib import Path; import sys; from pm import prepare_tools; "
        "from pm.store import current_target; "
        "prepare_tools(['pnpm'], out=Path(sys.argv[1]), target=current_target())",
        str(source / "tools"),
    ], cwd=source, check=True)
    facts.chmod(0o644)
    for lock in (environment / ".lock", source / "pm-runtime" / ".lock"):
        lock.unlink(missing_ok=True)


def main() -> int:
    import argparse
    import sys

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--requirements", required=True, type=Path)
    args = parser.parse_args()
    source = args.source.resolve()
    if not (source / "pm/build_env.py").is_file():
        raise ValueError("A supported PM base (v0.23.2+) is required; legacy installers are retired")
    requirements = [line.strip() for line in args.requirements.read_text().splitlines()
                    if line.strip() and not line.lstrip().startswith("#")]
    # Bootstrap from outside the application environment that PM will replace.
    sys.path.insert(0, str(source))
    from pm.paths import facts_path

    facts = facts_path()
    baseline = recorded_selection(facts)
    if baseline is None:
        raise ValueError("Base image lacks pm.build_env --record-selection; refusing an unrecorded environment")
    feature_requirements(source)
    project = source / "pyproject.toml"
    add_custom_extra(project, requirements)
    constrain_image_resolution(project)
    rebuild_pm_environment(source, baseline, facts)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

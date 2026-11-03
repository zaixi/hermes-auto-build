"""Offline build smoke checks; no provider calls or persistent services."""
from importlib import import_module, metadata
from io import BytesIO
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import tempfile
from install_image_dependencies import feature_requirements


def verify_cli_tools() -> None:
    for command in ("agent-browser", "lark-cli"):
        if not shutil.which(command):
            raise RuntimeError(f"Missing runtime CLI on PATH: {command}")
        subprocess.run([command, "--version"], check=True, timeout=30, cwd="/")
    # The terminal tool uses login shells, whose /etc/profile resets PATH.
    subprocess.run(["/bin/sh", "-lc",
                    "set -e; agent-browser --version; lark-cli --version"],
                   check=True, timeout=30, cwd="/")
    browser = os.environ.get("AGENT_BROWSER_EXECUTABLE_PATH")
    if not browser or not os.access(browser, os.X_OK):
        raise RuntimeError("Missing executable AGENT_BROWSER_EXECUTABLE_PATH")
    subprocess.run([browser, "--version"], check=True, timeout=30, cwd="/")
    # Exercise the CLI's actual browser launch under the runtime UID. The
    # local data URL needs no network, accounts, API keys or external service.
    # BuildKit on hosted runners cannot provide Chrome's userns sandbox.
    # Disable it only for this offline data-URL smoke, never in image ENV or
    # the runtime browser configuration. Pass identical flags on cleanup too.
    command = ["agent-browser", "--session", f"image-smoke-{os.getpid()}",
               "--args", "--no-sandbox"]
    try:
        subprocess.run(command + ["open", "data:text/html,<title>hermes-image-smoke</title>"],
                       check=True, timeout=60, cwd="/")
        result = subprocess.run(command + ["get", "title"], check=True,
                                capture_output=True, text=True, timeout=30, cwd="/")
        if "hermes-image-smoke" not in result.stdout:
            raise RuntimeError(f"Browser smoke returned unexpected title: {result.stdout!r}")
    finally:
        subprocess.run(command + ["close"], check=True, timeout=30, cwd="/")
    print("Runtime CLI, login-shell PATH and browser launch OK", flush=True)


def main() -> int:
    from packaging.requirements import Requirement

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("/opt/hermes"))
    parser.add_argument("--requirements", type=Path)
    parser.add_argument("--check-hermes", action="store_true")
    args = parser.parse_args()

    verify_cli_tools()

    custom = args.requirements or args.source / "requirements-custom.txt"
    specifications = [line.strip() for line in custom.read_text().splitlines()
                      if line.strip() and not line.lstrip().startswith("#")]
    for requirements in feature_requirements(args.source).values():
        specifications.extend(requirements)
    for specification in specifications:
        requirement = Requirement(specification)
        if requirement.marker and not requirement.marker.evaluate():
            continue
        installed = metadata.version(requirement.name)
        if requirement.specifier and installed not in requirement.specifier:
            raise RuntimeError(f"Unsatisfied image dependency: {requirement} (installed {installed})")
        print(f"Dependency OK: {requirement.name}=={installed}", flush=True)

    for module in ("pandas", "openpyxl", "hermes_keenable_web", "hindsight_client",
                   "hindsight_embed", "lark_oapi", "edge_tts", "pilk", "qrcode", "websockets"):
        import_module(module)
        print(f"Import OK: {module}", flush=True)

    import pandas as pd
    frame = pd.DataFrame({"姓名": ["测试"], "金额": [123]})
    workbook = BytesIO()
    frame.to_excel(workbook, index=False, engine="openpyxl")
    workbook.seek(0)
    pd.testing.assert_frame_equal(frame, pd.read_excel(workbook, engine="openpyxl"))
    print("XLSX round-trip OK", flush=True)

    import pilk
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        pcm, silk, decoded = root / "input.pcm", root / "audio.silk", root / "output.pcm"
        pcm.write_bytes(b"\0\0" * 24000)
        pilk.encode(str(pcm), str(silk), pcm_rate=24000, tencent=True)
        pilk.decode(str(silk), str(decoded), pcm_rate=24000)
        if silk.stat().st_size == 0 or decoded.stat().st_size == 0:
            raise RuntimeError("Silk native codec produced empty output")
    print("Silk native encode/decode OK", flush=True)

    from PIL import ImageFont
    font = ImageFont.truetype("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 24)
    if font.getbbox("中文财务报表") is None:
        raise RuntimeError("Chinese font could not be loaded")
    print("Chinese font load OK", flush=True)
    if args.check_hermes:
        import subprocess
        import sys

        subprocess.run([sys.executable, "-c", "import hermes_cli.main, tools.registry"],
                       cwd="/", check=True)
        subprocess.run([str(args.source / ".venv/bin/hermes"), "--version"],
                       cwd="/", check=True)
        facts = args.source / "tools/facts.json"
        if facts.exists():
            facts.read_text()
        if (args.source / "pm/build_env.py").is_file():
            # --version is metadata-only and cannot detect startup PM drift.
            subprocess.run([
                sys.executable, "-c",
                "from pathlib import Path; "
                "from hermes_cli.venv_sync import check_runtime; "
                f"problem = check_runtime(Path({str(args.source)!r})); "
                "raise SystemExit(problem)",
            ], cwd="/", check=True)
        print("Hermes source binding, CLI, runtime drift and metadata access OK", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

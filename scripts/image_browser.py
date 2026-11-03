"""Select the image's existing Chromium; never download or provision tools."""
import argparse
import os
from pathlib import Path
import shutil

MARKERS = ("chromium-executable-path", "agent-browser-executable-path")


def browser_path(marker_dir: Path, *, system_browser: str | None) -> Path | None:
    for name in MARKERS:
        marker = marker_dir / name
        if not marker.exists():
            continue
        value = marker.read_text(encoding="utf-8-sig").strip()
        binary = Path(value)
        if not value or not binary.is_absolute() or not binary.is_file() or not os.access(binary, os.X_OK):
            raise ValueError(f"Invalid browser marker {marker}: {value!r}")
        return binary
    if system_browser:
        binary = Path(system_browser)
        if binary.is_absolute() and binary.is_file() and os.access(binary, os.X_OK):
            return binary
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--marker-dir", type=Path, default=Path("/etc/hermes"))
    parser.add_argument("--link", type=Path)
    args = parser.parse_args()
    binary = browser_path(args.marker_dir, system_browser=shutil.which("chromium"))
    if args.link:
        if binary is None:
            raise RuntimeError("No image Chromium available after apt fallback")
        # This is a downstream-owned stable name, never a PM tool-store path.
        if args.link.is_symlink():
            args.link.unlink()
        args.link.symlink_to(binary)
    print(str(binary) if binary else "", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Backport #62930: normal check_fn False results are DEBUG, not WARNING.

Fails closed when upstream source is neither the known legacy block nor an
already-supported global non-warning implementation.
"""

from __future__ import annotations

import sys
from pathlib import Path

OLD = '''        # No recent success (or grace expired) — honor the failure; logged so silent tool
        # loss in quiet mode (subagents) is diagnosable.
        logger.warning(
            "check_fn %s %s; dependent tools will be unavailable this turn", _fn_label(fn), outcome,
            exc_info=exc_info)
'''

NEW = '''        # A normal False verdict means an optional capability is unavailable, not that
        # its probe crashed. Keep it diagnosable at DEBUG without flooding warning logs;
        # exceptions remain WARNING and recent-success flakes still warn above (#86417/#62930).
        log = logger.debug if outcome == "returned False" else logger.warning
        log(
            "check_fn %s %s; dependent tools will be unavailable this turn", _fn_label(fn), outcome,
            exc_info=exc_info)
'''

GLOBAL_FIX_MARKERS = (
    'logger.debug if outcome == "returned False" else logger.warning',
    'logger.info if outcome == "returned False" else logger.warning',
    'log = logger.warning if exc_info else logger.info',
    'logger.warning if raised else logger.debug',
    'logger.warning if raised else logger.info',
)


def main() -> int:
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/hermes/tools/registry.py")
    source = target.read_text(encoding="utf-8")

    has_old = OLD in source
    has_global_fix = any(marker in source for marker in GLOBAL_FIX_MARKERS)

    if has_global_fix and not has_old:
        print("check_fn False log-level fix already present upstream; skipping")
        return 0
    if has_old and not has_global_fix:
        if source.count(OLD) != 1:
            raise SystemExit(f"expected one legacy registry block, found {source.count(OLD)}")
        target.write_text(source.replace(OLD, NEW), encoding="utf-8")
        print("applied check_fn False WARNING-to-DEBUG backport")
        return 0

    raise SystemExit(
        "unsafe registry state: legacy and fixed markers are both present or both absent; "
        "review upstream before building"
    )


if __name__ == "__main__":
    raise SystemExit(main())

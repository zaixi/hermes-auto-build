#!/usr/bin/env python3
"""Regression checks for optional tool availability log levels."""

from __future__ import annotations

import logging
import os
import sys
import unittest

SOURCE_ROOT = os.environ.get("HERMES_SOURCE_ROOT", "/opt/hermes")
sys.path.insert(0, SOURCE_ROOT)

from tools.registry import _check_fn_cached, invalidate_check_fn_cache  # noqa: E402


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


class CheckFnFalseLogLevelTest(unittest.TestCase):
    def setUp(self) -> None:
        invalidate_check_fn_cache()
        self.logger = logging.getLogger("tools.registry")
        self.old_level = self.logger.level
        self.old_propagate = self.logger.propagate
        self.capture = _Capture()
        self.logger.handlers.append(self.capture)
        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False

    def tearDown(self) -> None:
        self.logger.handlers.remove(self.capture)
        self.logger.setLevel(self.old_level)
        self.logger.propagate = self.old_propagate
        invalidate_check_fn_cache()

    def _matching(self, label: str) -> list[logging.LogRecord]:
        return [r for r in self.capture.records if label in r.getMessage()]

    def test_false_is_non_warning_and_still_unavailable(self) -> None:
        def optional_mode_gate() -> bool:
            return False

        self.assertFalse(_check_fn_cached(optional_mode_gate))
        records = self._matching("optional_mode_gate")
        self.assertEqual(1, len(records))
        self.assertLess(records[0].levelno, logging.WARNING)
        self.assertIn("returned False", records[0].getMessage())

    def test_exception_stays_warning(self) -> None:
        def broken_dependency_probe() -> bool:
            raise RuntimeError("boom")

        self.assertFalse(_check_fn_cached(broken_dependency_probe))
        records = self._matching("broken_dependency_probe")
        self.assertEqual([logging.WARNING], [r.levelno for r in records])
        self.assertIn("raised", records[0].getMessage())
        self.assertIsNotNone(records[0].exc_info)


if __name__ == "__main__":
    unittest.main(verbosity=2)

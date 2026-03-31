from __future__ import annotations

import json
import os
import tempfile
import unittest

from egtsr_runtime.ops.logging import RuntimeLogEvent, RuntimeLogger


class TestLogging(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.log_path = os.path.join(self._tmp.name, "runtime.log")

    def tearDown(self):
        self._tmp.cleanup()

    def test_structured_log_written(self):
        """Log event writes valid JSON line"""
        logger = RuntimeLogger(self.log_path)
        logger.info("test.event")
        with open(self.log_path) as f:
            line = f.readline().strip()
        parsed = json.loads(line)
        self.assertIsInstance(parsed, dict)

    def test_log_levels(self):
        """info/warn/error produce correct level"""
        logger = RuntimeLogger(self.log_path)
        logger.info("ev.info")
        logger.warn("ev.warn")
        logger.error("ev.error")
        with open(self.log_path) as f:
            lines = [json.loads(l.strip()) for l in f if l.strip()]
        levels = [e["level"] for e in lines]
        self.assertEqual(levels, ["INFO", "WARN", "ERROR"])

    def test_log_event_fields(self):
        """ts, level, event_type, session_id, details all present"""
        logger = RuntimeLogger(self.log_path)
        logger.info("ev.full", session_id="sess-1", key="value")
        with open(self.log_path) as f:
            parsed = json.loads(f.readline().strip())
        self.assertIn("ts", parsed)
        self.assertIn("level", parsed)
        self.assertIn("event_type", parsed)
        self.assertIn("session_id", parsed)
        self.assertIn("details", parsed)
        self.assertEqual(parsed["session_id"], "sess-1")
        self.assertEqual(parsed["details"], {"key": "value"})
        self.assertEqual(parsed["event_type"], "ev.full")

    def test_details_none_when_empty(self):
        """details is None when no kwargs given"""
        logger = RuntimeLogger(self.log_path)
        logger.info("ev.empty")
        with open(self.log_path) as f:
            parsed = json.loads(f.readline().strip())
        self.assertIsNone(parsed["details"])

    def test_multiple_lines_appended(self):
        """Multiple log calls produce multiple lines"""
        logger = RuntimeLogger(self.log_path)
        logger.info("ev.1")
        logger.info("ev.2")
        logger.info("ev.3")
        with open(self.log_path) as f:
            lines = [l for l in f if l.strip()]
        self.assertEqual(len(lines), 3)


if __name__ == "__main__":
    unittest.main()

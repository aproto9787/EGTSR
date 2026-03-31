from __future__ import annotations

import json
import os
import tempfile
import unittest

from egtsr_runtime.ops.metrics import MetricsEmitter, COUNTER_SESSION_START


class TestMetrics(unittest.TestCase):
    def test_counter_increment(self):
        """incr increases counter value"""
        m = MetricsEmitter()
        m.incr(COUNTER_SESSION_START)
        self.assertEqual(m.get(COUNTER_SESSION_START), 1)
        m.incr(COUNTER_SESSION_START, 3)
        self.assertEqual(m.get(COUNTER_SESSION_START), 4)

    def test_export_json(self):
        """export_json returns all counters"""
        m = MetricsEmitter()
        m.incr("a", 2)
        m.incr("b", 5)
        data = m.export_json()
        self.assertEqual(data["a"], 2)
        self.assertEqual(data["b"], 5)

    def test_save_to_file(self):
        """save writes JSON to file"""
        m = MetricsEmitter()
        m.incr("x", 7)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "metrics.json")
            m.save(path)
            with open(path) as f:
                data = json.load(f)
        self.assertEqual(data["x"], 7)

    def test_default_counter_zero(self):
        """Unset counter returns 0"""
        m = MetricsEmitter()
        self.assertEqual(m.get("nonexistent"), 0)

    def test_multiple_counters_independent(self):
        """Different counter names are independent"""
        m = MetricsEmitter()
        m.incr("alpha", 10)
        m.incr("beta", 20)
        self.assertEqual(m.get("alpha"), 10)
        self.assertEqual(m.get("beta"), 20)


if __name__ == "__main__":
    unittest.main()

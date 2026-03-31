"""Tests for extended metrics (Step 08): timings, percentiles, MetricsWriter/Reader."""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from egtsr_runtime.ops.metrics import (
    COUNTER_SESSION_START,
    MetricsEmitter,
    MetricsReader,
    MetricsWriter,
    _percentile,
)


class TestPercentile(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(_percentile([], 50), 0.0)

    def test_single(self):
        self.assertEqual(_percentile([5.0], 50), 5.0)
        self.assertEqual(_percentile([5.0], 99), 5.0)

    def test_median(self):
        data = [1.0, 2.0, 3.0, 4.0, 5.0]
        self.assertAlmostEqual(_percentile(data, 50), 3.0)

    def test_p95(self):
        data = list(range(1, 101))  # 1..100
        p95 = _percentile([float(x) for x in data], 95)
        self.assertAlmostEqual(p95, 95.05, places=1)

    def test_two_values(self):
        self.assertAlmostEqual(_percentile([10.0, 20.0], 50), 15.0)


class TestMetricsEmitterTimings(unittest.TestCase):
    def test_record_and_percentile(self):
        m = MetricsEmitter()
        for v in [10.0, 20.0, 30.0, 40.0, 50.0]:
            m.record_timing("compile", v)
        self.assertAlmostEqual(m.percentile("compile", 50), 30.0)
        self.assertEqual(len(m.get_timings("compile")), 5)

    def test_timing_summary(self):
        m = MetricsEmitter()
        for v in [5.0, 10.0, 15.0, 20.0, 25.0]:
            m.record_timing("hook.ms", v)
        s = m.timing_summary("hook.ms")
        self.assertEqual(s["count"], 5)
        self.assertEqual(s["min"], 5.0)
        self.assertEqual(s["max"], 25.0)
        self.assertEqual(s["mean"], 15.0)
        self.assertAlmostEqual(s["p50"], 15.0)

    def test_empty_timing_summary(self):
        m = MetricsEmitter()
        s = m.timing_summary("nonexistent")
        self.assertEqual(s["count"], 0)

    def test_percentile_empty(self):
        m = MetricsEmitter()
        self.assertEqual(m.percentile("nonexistent", 50), 0.0)

    def test_export_includes_timings(self):
        m = MetricsEmitter()
        m.incr("counter_a", 5)
        m.record_timing("timing_b", 10.0)
        data = m.export_json()
        self.assertEqual(data["counter_a"], 5)
        self.assertIn("timing_b.summary", data)
        self.assertEqual(data["timing_b.summary"]["count"], 1)

    def test_backward_compat_counters(self):
        """Existing counter API still works."""
        m = MetricsEmitter()
        m.incr(COUNTER_SESSION_START)
        self.assertEqual(m.get(COUNTER_SESSION_START), 1)
        m.incr(COUNTER_SESSION_START, 3)
        self.assertEqual(m.get(COUNTER_SESSION_START), 4)


class TestMetricsWriter(unittest.TestCase):
    def test_write_and_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = MetricsWriter(tmp)
            writer.write_hook_timing("session_start", 12.5, session_id="sess-1")
            writer.write_hook_timing("post_tool_use", 8.3, session_id="sess-1")
            writer.write_fallback("compiler", "inconsistency", session_id="sess-1")

            reader = MetricsReader(tmp)
            events = reader.read_all()
            self.assertEqual(len(events), 3)

            # Check timing events
            timings = reader.query(event_type="hook.session_start.timing")
            self.assertEqual(len(timings), 1)
            self.assertAlmostEqual(timings[0]["duration_ms"], 12.5)

            # Check fallback events
            fallbacks = reader.fallback_summary()
            self.assertIn("compiler", fallbacks)
            self.assertEqual(fallbacks["compiler"]["inconsistency"], 1)

    def test_hook_timing_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = MetricsWriter(tmp)
            for ms in [10.0, 12.0, 11.0, 13.0, 9.0]:
                writer.write_hook_timing("compile", ms)

            reader = MetricsReader(tmp)
            summary = reader.hook_timing_summary()
            self.assertIn("compile", summary)
            self.assertEqual(summary["compile"]["count"], 5)
            self.assertEqual(summary["compile"]["min"], 9.0)
            self.assertEqual(summary["compile"]["max"], 13.0)

    def test_write_compile_timing(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = MetricsWriter(tmp)
            writer.write_compile_timing(25.0, mode="incremental", session_id="s1")

            reader = MetricsReader(tmp)
            events = reader.query(event_type="compiler.render.timing")
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["mode"], "incremental")

    def test_write_invalidation_timing(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = MetricsWriter(tmp)
            writer.write_invalidation_timing(3.5, changed_count=2, impacted_count=5)

            reader = MetricsReader(tmp)
            events = reader.query(event_type="invalidation.apply.timing")
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["changed_count"], 2)

    def test_empty_reader(self):
        with tempfile.TemporaryDirectory() as tmp:
            reader = MetricsReader(tmp)
            self.assertEqual(reader.read_all(), [])
            self.assertEqual(reader.hook_timing_summary(), {})
            self.assertEqual(reader.fallback_summary(), {})


class TestMetricsReaderFiltering(unittest.TestCase):
    def test_filter_by_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            writer = MetricsWriter(tmp)
            writer.write_hook_timing("compile", 10.0, session_id="s1")
            writer.write_hook_timing("compile", 20.0, session_id="s2")
            writer.write_hook_timing("compile", 30.0, session_id="s1")

            reader = MetricsReader(tmp)
            s1_events = reader.query(session_id="s1")
            self.assertEqual(len(s1_events), 2)


if __name__ == "__main__":
    unittest.main()

"""Tests for regression gate (Step 08)."""
from __future__ import annotations

import json
import os
import tempfile
import unittest

from egtsr_runtime.benchmarks.baseline import BaselineReport, HookLatencyEntry, save_baseline_report
from egtsr_runtime.benchmarks.regression_gate import (
    GateThresholds,
    RegressionGate,
    load_baseline,
    save_gate_report,
)
from egtsr_runtime.benchmarks.scale import ScalePoint, ScaleReport


class TestRegressionGateFunctional(unittest.TestCase):
    """Gate 1: functional checks."""

    def _report_with_scenarios(self, scenarios: list[dict]) -> BaselineReport:
        return BaselineReport(
            timestamp="20260331T120000Z",
            hook_latencies=[HookLatencyEntry("compile", 10.0)],
            scenario_results=scenarios,
        )

    def test_all_pass(self):
        report = self._report_with_scenarios([
            {"name": "forced_split", "audit_pass": True, "stale_leak_count": 0},
            {"name": "stale_injection", "audit_pass": True, "stale_leak_count": 0},
        ])
        gate = RegressionGate()
        result = gate.evaluate(report)
        functional_checks = [c for c in result.checks if c.name.startswith("functional.")]
        self.assertTrue(all(c.passed for c in functional_checks))

    def test_audit_fail(self):
        report = self._report_with_scenarios([
            {"name": "forced_split", "audit_pass": False, "stale_leak_count": 0},
        ])
        gate = RegressionGate()
        result = gate.evaluate(report)
        self.assertFalse(result.overall_pass)

    def test_stale_leak(self):
        report = self._report_with_scenarios([
            {"name": "forced_split", "audit_pass": True, "stale_leak_count": 2},
        ])
        gate = RegressionGate()
        result = gate.evaluate(report)
        stale_check = [c for c in result.checks if "stale_leak" in c.name][0]
        self.assertFalse(stale_check.passed)


class TestRegressionGateLatency(unittest.TestCase):
    """Gate 2: latency checks."""

    def test_p95_within_threshold(self):
        report = BaselineReport(
            timestamp="20260331T120000Z",
            hook_latencies=[
                HookLatencyEntry("compile", 10.0),
                HookLatencyEntry("seed", 15.0),
                HookLatencyEntry("invalidation", 8.0),
            ],
        )
        gate = RegressionGate(GateThresholds(latency_p95_max_ms=200.0))
        result = gate.evaluate(report)
        p95_check = [c for c in result.checks if c.name == "latency.p95_absolute"][0]
        self.assertTrue(p95_check.passed)

    def test_p95_exceeds_threshold(self):
        report = BaselineReport(
            timestamp="20260331T120000Z",
            hook_latencies=[
                HookLatencyEntry("compile", 300.0),
                HookLatencyEntry("seed", 250.0),
            ],
        )
        gate = RegressionGate(GateThresholds(latency_p95_max_ms=200.0))
        result = gate.evaluate(report)
        p95_check = [c for c in result.checks if c.name == "latency.p95_absolute"][0]
        self.assertFalse(p95_check.passed)

    def test_regression_vs_baseline(self):
        baseline = BaselineReport(
            timestamp="20260330T120000Z",
            hook_latencies=[HookLatencyEntry("compile", 10.0)],
        )
        # 50% worse
        current = BaselineReport(
            timestamp="20260331T120000Z",
            hook_latencies=[HookLatencyEntry("compile", 15.0)],
        )
        gate = RegressionGate(GateThresholds(latency_p95_regression_pct=0.10))
        result = gate.evaluate(current, baseline=baseline)
        reg_check = [c for c in result.checks if c.name == "latency.p95_regression"][0]
        self.assertFalse(reg_check.passed)

    def test_no_regression(self):
        baseline = BaselineReport(
            timestamp="20260330T120000Z",
            hook_latencies=[HookLatencyEntry("compile", 10.0)],
        )
        current = BaselineReport(
            timestamp="20260331T120000Z",
            hook_latencies=[HookLatencyEntry("compile", 10.5)],  # 5% worse
        )
        gate = RegressionGate(GateThresholds(latency_p95_regression_pct=0.10))
        result = gate.evaluate(current, baseline=baseline)
        reg_check = [c for c in result.checks if c.name == "latency.p95_regression"][0]
        self.assertTrue(reg_check.passed)

    def test_no_latency_data(self):
        report = BaselineReport(timestamp="20260331T120000Z")
        gate = RegressionGate()
        result = gate.evaluate(report)
        data_check = [c for c in result.checks if c.name == "latency.data_available"][0]
        self.assertFalse(data_check.passed)


class TestRegressionGateScale(unittest.TestCase):
    """Gate 3: scaling checks."""

    def test_acceptable_slope(self):
        scale = ScaleReport(
            timestamp="20260331T120000Z",
            points=[
                ScalePoint(1, 2, 2, 5.0, 2.0, 100),
                ScalePoint(5, 10, 10, 10.0, 3.0, 200),
                ScalePoint(10, 20, 20, 15.0, 4.0, 400),
            ],
        )
        scale.compute_slopes()
        gate = RegressionGate(GateThresholds(scale_slope_max=5.0))
        result = gate.evaluate(
            BaselineReport(
                timestamp="20260331T120000Z",
                hook_latencies=[HookLatencyEntry("compile", 10.0)],
            ),
            scale_report=scale,
        )
        slope_check = [c for c in result.checks if c.name == "scale.compile_slope"][0]
        self.assertTrue(slope_check.passed)

    def test_high_slope_fails(self):
        scale = ScaleReport(
            timestamp="20260331T120000Z",
            points=[
                ScalePoint(1, 2, 2, 5.0, 2.0, 100),
                ScalePoint(5, 10, 10, 50.0, 3.0, 200),
                ScalePoint(10, 20, 20, 100.0, 4.0, 400),
            ],
        )
        scale.compute_slopes()
        gate = RegressionGate(GateThresholds(scale_slope_max=5.0))
        result = gate.evaluate(
            BaselineReport(
                timestamp="20260331T120000Z",
                hook_latencies=[HookLatencyEntry("compile", 10.0)],
            ),
            scale_report=scale,
        )
        slope_check = [c for c in result.checks if c.name == "scale.compile_slope"][0]
        self.assertFalse(slope_check.passed)


class TestRegressionGateShadow(unittest.TestCase):
    """Gate 4: shadow diff checks."""

    def test_no_critical_diffs(self):
        shadow = [
            {"audit_match": True, "rendered_text_identical": True},
            {"audit_match": True, "rendered_text_identical": True},
        ]
        gate = RegressionGate()
        result = gate.evaluate(
            BaselineReport(
                timestamp="20260331T120000Z",
                hook_latencies=[HookLatencyEntry("compile", 10.0)],
            ),
            shadow_results=shadow,
        )
        shadow_check = [c for c in result.checks if c.name == "shadow.critical_diffs"][0]
        self.assertTrue(shadow_check.passed)

    def test_critical_diff_fails(self):
        shadow = [
            {"audit_match": False, "rendered_text_identical": True},
        ]
        gate = RegressionGate()
        result = gate.evaluate(
            BaselineReport(
                timestamp="20260331T120000Z",
                hook_latencies=[HookLatencyEntry("compile", 10.0)],
            ),
            shadow_results=shadow,
        )
        shadow_check = [c for c in result.checks if c.name == "shadow.critical_diffs"][0]
        self.assertFalse(shadow_check.passed)


class TestBaselineLoadSave(unittest.TestCase):
    """Test baseline report load/save round-trip."""

    def test_round_trip(self):
        report = BaselineReport(
            timestamp="20260331T120000Z",
            hook_latencies=[
                HookLatencyEntry("compile", 10.5),
                HookLatencyEntry("seed", 5.2),
            ],
            obligation_count=3,
            scenario_results=[{"name": "test", "audit_pass": True, "stale_leak_count": 0}],
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = save_baseline_report(report, tmp)
            loaded = load_baseline(path)
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.timestamp, "20260331T120000Z")
        self.assertEqual(len(loaded.hook_latencies), 2)
        self.assertEqual(loaded.obligation_count, 3)

    def test_load_missing(self):
        self.assertIsNone(load_baseline("/nonexistent/path.json"))


class TestGateReportSave(unittest.TestCase):
    def test_save_and_read(self):
        gate = RegressionGate()
        report = BaselineReport(
            timestamp="20260331T120000Z",
            hook_latencies=[HookLatencyEntry("compile", 10.0)],
            scenario_results=[{"name": "test", "audit_pass": True, "stale_leak_count": 0}],
        )
        gate_report = gate.evaluate(report)
        with tempfile.TemporaryDirectory() as tmp:
            path = save_gate_report(gate_report, tmp)
            with open(path) as f:
                data = json.load(f)
        self.assertIn("overall_pass", data)
        self.assertIn("checks", data)
        self.assertTrue(data["overall_pass"])


class TestScaleSlope(unittest.TestCase):
    def test_compute_slopes(self):
        report = ScaleReport(
            timestamp="20260331T120000Z",
            points=[
                ScalePoint(1, 2, 2, 10.0, 5.0, 100),
                ScalePoint(10, 20, 20, 100.0, 50.0, 1000),
            ],
        )
        report.compute_slopes()
        self.assertGreater(report.compile_slope, 0)
        self.assertGreater(report.invalidation_slope, 0)

    def test_single_point_no_slope(self):
        report = ScaleReport(
            timestamp="20260331T120000Z",
            points=[ScalePoint(1, 2, 2, 10.0, 5.0, 100)],
        )
        report.compute_slopes()
        self.assertEqual(report.compile_slope, 0.0)


if __name__ == "__main__":
    unittest.main()

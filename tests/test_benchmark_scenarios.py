from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from egtsr_runtime.benchmarks import (
    BenchmarkReporter,
    BenchmarkRunner,
    ForcedSplitScenario,
    GateCheck,
    GoNoGoEvaluator,
    RegressionGateReport,
    RepeatedFailureScenario,
    ScenarioResult,
    StaleInjectionScenario,
    generate_judgment_report,
)


class TestBenchmarkScenarios(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.reporter = BenchmarkReporter()
        self.runner = BenchmarkRunner()
        self.evaluator = GoNoGoEvaluator()

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_forced_split_reproducible(self):
        """Forced split scenario runs and returns executed=True, audit detects stale"""
        result = ForcedSplitScenario().run(self._db_path("forced_split"))

        self.assertTrue(result.executed)
        self.assertTrue(result.audit_pass)  # audit correctly detects stale

    def test_stale_injection_reproducible(self):
        """Stale injection scenario runs and returns executed=True"""
        result = StaleInjectionScenario().run(self._db_path("stale_injection"))

        self.assertTrue(result.executed)
        self.assertTrue(result.audit_pass)  # audit correctly detects stale

    def test_repeated_failure_reproducible(self):
        """Repeated failure scenario runs and returns executed=True"""
        result = RepeatedFailureScenario().run(self._db_path("repeated_failure"))

        self.assertTrue(result.executed)
        self.assertTrue(result.audit_pass)

    def test_same_budget_comparison(self):
        """3-way comparison produces results for all 3 methods"""
        comparison = self.runner.run_same_budget_comparison(budget=900)

        self.assertCountEqual(
            comparison.keys(),
            ["forced_split", "stale_injection", "repeated_failure"],
        )
        for counts in comparison.values():
            self.assertIn("raw", counts)
            self.assertIn("naive", counts)
            self.assertIn("egtsr", counts)

    def test_csv_report_generated(self):
        """CSV report has correct columns and >= 3 rows"""
        results = self.runner.run_all()
        comparison = self.runner.run_same_budget_comparison()

        csv_text = self.reporter.generate_csv(results, comparison)
        lines = [line for line in csv_text.strip().splitlines() if line.strip()]

        self.assertGreaterEqual(len(lines), 4)
        self.assertIn("scenario", lines[0])
        self.assertIn("raw_tokens", lines[0])
        self.assertIn("egtsr_tokens", lines[0])

    def test_json_report_valid(self):
        """JSON report is valid and contains scenarios + summary"""
        results = self.runner.run_all()
        comparison = self.runner.run_same_budget_comparison()
        verdict = self.evaluator.evaluate(results)

        payload = self.reporter.generate_json(results, comparison, verdict)

        self.assertIsInstance(json.dumps(payload), str)
        self.assertIn("scenarios", payload)
        self.assertIn("summary", payload)
        self.assertEqual(len(payload["scenarios"]), 3)

    def test_go_no_go_continue(self):
        """All-pass results -> verdict = continue"""
        results = [
            ScenarioResult(
                name="one",
                executed=True,
                audit_pass=True,
                token_count=60,
                resume_safety=True,
                details={"raw_token_count": 120},
            ),
            ScenarioResult(
                name="two",
                executed=True,
                audit_pass=True,
                token_count=70,
                resume_safety=True,
                details={"raw_token_count": 140},
            ),
        ]

        self.assertEqual(self.evaluator.evaluate(results), "continue")

    def test_go_no_go_stop_on_omission(self):
        """audit_pass=False -> verdict = stop"""
        results = [
            ScenarioResult(
                name="omission",
                executed=True,
                audit_pass=False,
                token_count=10,
                resume_safety=True,
                details={"raw_token_count": 100},
            )
        ]

        self.assertEqual(self.evaluator.evaluate(results), "stop")

    def test_go_no_go_stop_on_stale_leak(self):
        """stale_leak_count>0 -> verdict = stop"""
        results = [
            ScenarioResult(
                name="leak",
                executed=True,
                audit_pass=True,
                stale_leak_count=1,
                token_count=10,
                resume_safety=True,
                details={"raw_token_count": 100},
            )
        ]

        self.assertEqual(self.evaluator.evaluate(results), "stop")

    def test_memo_generated(self):
        """Go/No-Go memo is non-empty markdown"""
        results = self.runner.run_all()
        memo = self.reporter.generate_memo(results, "continue")

        self.assertTrue(memo.strip())
        self.assertTrue(memo.startswith("#"))

    def test_markdown_report_structure(self):
        """Markdown report contains summary table, Go/No-Go section, and detailed results"""
        results = self.runner.run_all()
        comparison = self.runner.run_same_budget_comparison()
        verdict = self.evaluator.evaluate(results)

        md = self.reporter.generate_markdown_report(results, comparison, verdict)

        self.assertIn("# EGTSR Benchmark Report", md)
        self.assertIn("## Summary", md)
        self.assertIn("| Scenario | Raw | Naive | EGTSR | Delta |", md)
        self.assertIn("## Go/No-Go Judgment", md)
        self.assertIn("**Verdict**:", md)
        self.assertIn("### Criteria", md)
        self.assertIn("## Detailed Results", md)
        for name in ("forced_split", "stale_injection", "repeated_failure"):
            self.assertIn(f"### {name}", md)

    def test_markdown_report_verdict_labels(self):
        """Markdown report maps verdict strings to proper labels"""
        results = [
            ScenarioResult(
                name="test",
                executed=True,
                audit_pass=True,
                token_count=50,
                resume_safety=True,
                details={"raw_token_count": 200, "token_savings_pct": 0.75},
            ),
        ]
        comparison = {"test": {"raw": 200, "naive": 150, "egtsr": 50}}

        md = self.reporter.generate_markdown_report(results, comparison, "continue")
        self.assertIn("**Verdict**: Continue", md)

        md = self.reporter.generate_markdown_report(results, comparison, "shrink")
        self.assertIn("**Verdict**: Shrink", md)

    def test_judgment_report_structure(self):
        """generate_judgment_report produces valid markdown with check table"""
        report = RegressionGateReport(
            timestamp="2026-04-01T12:00:00Z",
            overall_pass=False,
            checks=[
                GateCheck(
                    name="functional.test.audit",
                    passed=True,
                    actual=1,
                    threshold=1,
                    message="Audit passed for test",
                ),
                GateCheck(
                    name="latency.p95_absolute",
                    passed=False,
                    actual=250.0,
                    threshold=200.0,
                    message="p95=250.0ms (max=200.0ms)",
                ),
            ],
        )

        md = generate_judgment_report(report)

        self.assertIn("# Regression Gate Judgment", md)
        self.assertIn("**Overall**: FAIL", md)
        self.assertIn("functional.test.audit", md)
        self.assertIn("PASS", md)
        self.assertIn("FAIL", md)
        self.assertIn("## Failed Checks", md)
        self.assertIn("latency.p95_absolute", md)

    def test_judgment_report_all_pass(self):
        """generate_judgment_report with all checks passing has no Failed Checks section"""
        report = RegressionGateReport(
            timestamp="2026-04-01T12:00:00Z",
            overall_pass=True,
            checks=[
                GateCheck(
                    name="functional.test.audit",
                    passed=True,
                    actual=1,
                    threshold=1,
                    message="Audit passed",
                ),
            ],
        )

        md = generate_judgment_report(report)

        self.assertIn("**Overall**: PASS", md)
        self.assertNotIn("## Failed Checks", md)

    def _db_path(self, name: str) -> str:
        return str(Path(self.tmp_dir.name) / f"{name}.sqlite3")


if __name__ == "__main__":
    unittest.main()

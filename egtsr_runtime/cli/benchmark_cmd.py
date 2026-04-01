"""CLI wrapper for benchmark harness."""
from __future__ import annotations

import json
import sys


def run_benchmark(project_dir: str = ".", fmt: str = "json") -> None:
    """Run all benchmarks and print report."""
    del project_dir
    from egtsr_runtime.benchmarks import BenchmarkReporter, BenchmarkRunner, GoNoGoEvaluator

    runner = BenchmarkRunner()
    reporter = BenchmarkReporter()
    evaluator = GoNoGoEvaluator()

    results = runner.run_all()
    comparison = runner.run_same_budget_comparison()
    verdict = evaluator.evaluate(results)

    if fmt == "markdown":
        print(reporter.generate_markdown_report(results, comparison, verdict))
    else:
        report = reporter.generate_json(results, comparison, verdict)
        print(json.dumps(report, indent=2, ensure_ascii=False))


def run_benchmark_latency(reports_dir: str | None = None) -> None:
    """Run latency benchmark and print report."""
    from egtsr_runtime.benchmarks import LatencyBenchmark

    bench = LatencyBenchmark()
    report = bench.run(reports_dir=reports_dir)
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))


def run_benchmark_latency_percentiles(
    iterations: int = 10,
    reports_dir: str | None = None,
) -> None:
    """Run multi-iteration latency benchmark with percentile output."""
    from egtsr_runtime.benchmarks import LatencyBenchmark

    bench = LatencyBenchmark()
    report = bench.run_with_percentiles(iterations=iterations, reports_dir=reports_dir)
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))


def run_benchmark_scale(reports_dir: str | None = None) -> None:
    """Run scale benchmark and print report."""
    from egtsr_runtime.benchmarks import ScaleBenchmark

    bench = ScaleBenchmark()
    report = bench.run_scale(reports_dir=reports_dir)
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))


def run_benchmark_shadow_diff(reports_dir: str | None = None) -> None:
    """Run shadow-diff benchmark and print report."""
    from egtsr_runtime.benchmarks import ShadowDiffBenchmark

    bench = ShadowDiffBenchmark()
    results = bench.run(reports_dir=reports_dir)
    payload = [
        {
            "token_delta": d.token_delta,
            "audit_match": d.audit_match,
            "block_count_match": d.block_count_match,
            "rendered_text_identical": d.rendered_text_identical,
        }
        for d in results
    ]
    print(json.dumps(payload, indent=2, ensure_ascii=False))


def run_benchmark_cold_warm(reports_dir: str | None = None) -> None:
    """Run cold vs warm daemon latency benchmark."""
    from egtsr_runtime.benchmarks import ColdWarmBenchmark

    bench = ColdWarmBenchmark()
    report = bench.run(reports_dir=reports_dir)
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))


def run_benchmark_migration(reports_dir: str | None = None) -> None:
    """Run migration/backfill benchmark."""
    from egtsr_runtime.benchmarks import MigrationBenchmark

    bench = MigrationBenchmark()
    report = bench.run_bench(reports_dir=reports_dir)
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))


def run_benchmark_gate(
    baseline_path: str | None = None,
    reports_dir: str | None = None,
) -> int:
    """Run regression gate: compare current benchmarks against baseline.

    Returns 0 on PASS, 1 on FAIL.
    """
    from egtsr_runtime.benchmarks import (
        LatencyBenchmark,
        RegressionGate,
        ScaleBenchmark,
        ShadowDiffBenchmark,
        load_baseline,
        save_gate_report,
    )

    baseline = load_baseline(baseline_path) if baseline_path else None

    # Run current benchmarks
    latency_report = LatencyBenchmark().run(reports_dir=reports_dir)
    scale_report = ScaleBenchmark().run_scale(reports_dir=reports_dir)
    shadow_results = ShadowDiffBenchmark().run(reports_dir=reports_dir)

    gate = RegressionGate()
    gate_report = gate.evaluate(
        current=latency_report,
        baseline=baseline,
        scale_report=scale_report,
        shadow_results=shadow_results,
    )

    if reports_dir:
        save_gate_report(gate_report, reports_dir)

    print(json.dumps(gate_report.to_dict(), indent=2, ensure_ascii=False))

    status = "PASS" if gate_report.overall_pass else "FAIL"
    failed = [c for c in gate_report.checks if not c.passed]
    print(f"\n--- Regression Gate: {status} ---", file=sys.stderr)
    if failed:
        for c in failed:
            print(f"  FAIL: {c.name} — {c.message}", file=sys.stderr)

    return 0 if gate_report.overall_pass else 1


def run_metrics(metrics_dir: str) -> None:
    """Show aggregated metrics from .egtsr/metrics/."""
    from egtsr_runtime.ops.metrics import MetricsReader

    reader = MetricsReader(metrics_dir)
    output: dict = {}

    hook_summary = reader.hook_timing_summary()
    if hook_summary:
        output["hook_timings"] = hook_summary

    fallback_summary = reader.fallback_summary()
    if fallback_summary:
        output["fallbacks"] = fallback_summary

    total = len(reader.read_all())
    output["total_events"] = total

    if not output.get("hook_timings") and not output.get("fallbacks"):
        output["message"] = "No metrics recorded yet"

    print(json.dumps(output, indent=2, ensure_ascii=False))

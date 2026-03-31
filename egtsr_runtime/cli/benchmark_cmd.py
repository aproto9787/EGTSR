"""CLI wrapper for benchmark harness."""
from __future__ import annotations

import json

from egtsr_runtime.benchmarks import BenchmarkReporter, BenchmarkRunner, GoNoGoEvaluator


def run_benchmark(project_dir: str = ".") -> None:
    """Run all benchmarks and print report."""
    del project_dir
    runner = BenchmarkRunner()
    reporter = BenchmarkReporter()
    evaluator = GoNoGoEvaluator()

    results = runner.run_all()
    comparison = runner.run_same_budget_comparison()
    verdict = evaluator.evaluate(results)
    report = reporter.generate_json(results, comparison, verdict)
    print(json.dumps(report, indent=2, ensure_ascii=False))

#!/usr/bin/env python3
"""EGTSR Benchmark Demo — run all scenarios and generate Go/No-Go report.
Usage: python3 scripts/run_benchmark_demo.py
"""
from egtsr_runtime.benchmarks.runner import BenchmarkRunner
from egtsr_runtime.benchmarks.reports import BenchmarkReporter
from egtsr_runtime.benchmarks.evaluator import GoNoGoEvaluator


def main():
    runner = BenchmarkRunner()
    results = runner.run_all()
    comparison = runner.run_same_budget_comparison()

    evaluator = GoNoGoEvaluator()
    verdict = evaluator.evaluate(results)

    reporter = BenchmarkReporter()
    print(reporter.generate_csv(results, comparison))
    print(f"\nVerdict: {verdict}")
    print(reporter.generate_memo(results, verdict))


if __name__ == "__main__":
    main()

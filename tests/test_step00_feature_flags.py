"""Tests for Step 00: RuntimeConfig feature flags, timer, diff schema, benchmarks."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from egtsr_runtime.config import RuntimeConfig, apply_overrides, load_runtime_flags


class TestRuntimeConfigDefaults(unittest.TestCase):
    """Feature flags are all default-off and runtime_mode is legacy."""

    def test_default_runtime_mode(self) -> None:
        cfg = RuntimeConfig(repo_root="/r", egtsr_dir="/r/.egtsr", db_path="/r/.egtsr/session.db")
        self.assertEqual(cfg.runtime_mode, "legacy")

    def test_default_flags_off(self) -> None:
        cfg = RuntimeConfig(repo_root="/r", egtsr_dir="/r/.egtsr", db_path="/r/.egtsr/session.db")
        self.assertFalse(cfg.enable_daemon)
        self.assertFalse(cfg.enable_incremental_compile)
        self.assertFalse(cfg.enable_projection_tables)
        self.assertFalse(cfg.enable_reverse_index)

    def test_backward_compat_fields(self) -> None:
        cfg = RuntimeConfig(repo_root="/r", egtsr_dir="/r/.egtsr", db_path="/r/.egtsr/session.db")
        self.assertFalse(cfg.enable_compact_hooks)
        self.assertEqual(cfg.max_decision_tokens, 900)


class TestLoadRuntimeFlags(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.egtsr_dir = self.tmp.name

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_missing_file(self) -> None:
        self.assertEqual(load_runtime_flags(self.egtsr_dir), {})

    def test_valid_json(self) -> None:
        flags_path = Path(self.egtsr_dir) / "runtime_flags.json"
        flags_path.write_text(json.dumps({"enable_daemon": True, "runtime_mode": "shadow"}))
        result = load_runtime_flags(self.egtsr_dir)
        self.assertTrue(result["enable_daemon"])
        self.assertEqual(result["runtime_mode"], "shadow")

    def test_invalid_json(self) -> None:
        flags_path = Path(self.egtsr_dir) / "runtime_flags.json"
        flags_path.write_text("not-json{{{")
        self.assertEqual(load_runtime_flags(self.egtsr_dir), {})


class TestApplyOverrides(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.egtsr_dir = self.tmp.name
        self._env_backup: dict[str, str | None] = {}

    def tearDown(self) -> None:
        self.tmp.cleanup()
        for key, val in self._env_backup.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val

    def _set_env(self, key: str, val: str) -> None:
        self._env_backup.setdefault(key, os.environ.get(key))
        os.environ[key] = val

    def _make_config(self) -> RuntimeConfig:
        return RuntimeConfig(
            repo_root="/r", egtsr_dir=self.egtsr_dir, db_path="/r/.egtsr/session.db"
        )

    def test_file_override(self) -> None:
        flags_path = Path(self.egtsr_dir) / "runtime_flags.json"
        flags_path.write_text(json.dumps({"enable_daemon": True, "runtime_mode": "daemon"}))
        cfg = apply_overrides(self._make_config())
        self.assertTrue(cfg.enable_daemon)
        self.assertEqual(cfg.runtime_mode, "daemon")

    def test_env_overrides_file(self) -> None:
        flags_path = Path(self.egtsr_dir) / "runtime_flags.json"
        flags_path.write_text(json.dumps({"enable_daemon": True}))
        self._set_env("EGTSR_ENABLE_DAEMON", "false")
        cfg = apply_overrides(self._make_config())
        self.assertFalse(cfg.enable_daemon)

    def test_env_runtime_mode(self) -> None:
        self._set_env("EGTSR_RUNTIME_MODE", "shadow")
        cfg = apply_overrides(self._make_config())
        self.assertEqual(cfg.runtime_mode, "shadow")

    def test_invalid_mode_ignored(self) -> None:
        self._set_env("EGTSR_RUNTIME_MODE", "turbo")
        cfg = apply_overrides(self._make_config())
        self.assertEqual(cfg.runtime_mode, "legacy")


class TestHookTimer(unittest.TestCase):
    def test_timed_hook_returns_result_and_timing(self) -> None:
        from egtsr_runtime.hooks.timer import clear_timings, get_timings, timed_hook

        clear_timings()
        result, timing = timed_hook("test_hook", lambda: 42)
        self.assertEqual(result, 42)
        self.assertEqual(timing.hook_name, "test_hook")
        self.assertGreater(timing.duration_ms, 0)
        self.assertEqual(len(get_timings()), 1)
        clear_timings()
        self.assertEqual(len(get_timings()), 0)


class TestDiffSchema(unittest.TestCase):
    def test_compute_identical(self) -> None:
        from egtsr_runtime.benchmarks.diff_schema import CompileDiffResult, CompileSnapshot

        snap = CompileSnapshot(
            path_label="legacy", rendered_text="hello", token_estimate=100,
            obligation_count=1, block_count=1, audit_passed=True,
        )
        cand = CompileSnapshot(
            path_label="candidate", rendered_text="hello", token_estimate=100,
            obligation_count=1, block_count=1, audit_passed=True,
        )
        diff = CompileDiffResult(legacy=snap, candidate=cand)
        diff.compute()
        self.assertEqual(diff.token_delta, 0)
        self.assertTrue(diff.audit_match)
        self.assertTrue(diff.block_count_match)
        self.assertTrue(diff.rendered_text_identical)

    def test_compute_divergent(self) -> None:
        from egtsr_runtime.benchmarks.diff_schema import CompileDiffResult, CompileSnapshot

        snap = CompileSnapshot(path_label="legacy", token_estimate=100, audit_passed=True)
        cand = CompileSnapshot(path_label="candidate", token_estimate=80, audit_passed=False)
        diff = CompileDiffResult(legacy=snap, candidate=cand)
        diff.compute()
        self.assertEqual(diff.token_delta, -20)
        self.assertFalse(diff.audit_match)


class TestBaselineReport(unittest.TestCase):
    def test_save_and_load(self) -> None:
        from egtsr_runtime.benchmarks.baseline import BaselineReport, HookLatencyEntry, save_baseline_report

        with tempfile.TemporaryDirectory() as tmp:
            report = BaselineReport(
                timestamp="20260331T100000Z",
                hook_latencies=[HookLatencyEntry(hook_name="compile", duration_ms=12.5)],
                obligation_count=3,
            )
            path = save_baseline_report(report, tmp)
            self.assertTrue(Path(path).exists())
            with open(path) as fh:
                data = json.load(fh)
            self.assertEqual(data["timestamp"], "20260331T100000Z")
            self.assertEqual(len(data["hook_latencies"]), 1)
            self.assertEqual(data["obligation_count"], 3)


class TestLatencyBenchmark(unittest.TestCase):
    def test_latency_runs(self) -> None:
        from egtsr_runtime.benchmarks.latency import LatencyBenchmark

        bench = LatencyBenchmark()
        report = bench.run()
        self.assertGreater(len(report.hook_latencies), 0)
        self.assertGreater(report.compile_duration_ms, 0)


class TestScaleBenchmark(unittest.TestCase):
    def test_scale_runs(self) -> None:
        from egtsr_runtime.benchmarks.scale import ScaleBenchmark

        bench = ScaleBenchmark(sizes=[1, 3])
        report = bench.run_scale()
        self.assertEqual(len(report.points), 2)
        self.assertEqual(report.points[0].obligation_count, 1)
        self.assertEqual(report.points[1].obligation_count, 3)


class TestShadowDiffBenchmark(unittest.TestCase):
    def test_shadow_diff_runs(self) -> None:
        from egtsr_runtime.benchmarks.shadow_diff import ShadowDiffBenchmark

        bench = ShadowDiffBenchmark()
        results = bench.run()
        self.assertEqual(len(results), 2)
        for diff in results:
            self.assertTrue(diff.audit_match)
            self.assertTrue(diff.rendered_text_identical)
            self.assertEqual(diff.token_delta, 0)


class TestCLIBenchmarkSubcommands(unittest.TestCase):
    def test_latency_subcommand_parses(self) -> None:
        from egtsr_runtime.cli.main import build_parser

        parser = build_parser()
        args = parser.parse_args(["benchmark", "latency"])
        self.assertEqual(args.command, "benchmark")
        self.assertEqual(args.bench_mode, "latency")

    def test_scale_subcommand_parses(self) -> None:
        from egtsr_runtime.cli.main import build_parser

        parser = build_parser()
        args = parser.parse_args(["benchmark", "scale"])
        self.assertEqual(args.bench_mode, "scale")

    def test_shadow_diff_subcommand_parses(self) -> None:
        from egtsr_runtime.cli.main import build_parser

        parser = build_parser()
        args = parser.parse_args(["benchmark", "shadow-diff"])
        self.assertEqual(args.bench_mode, "shadow-diff")

    def test_bare_benchmark_still_works(self) -> None:
        from egtsr_runtime.cli.main import build_parser

        parser = build_parser()
        args = parser.parse_args(["benchmark"])
        self.assertEqual(args.command, "benchmark")
        self.assertIsNone(args.bench_mode)


if __name__ == "__main__":
    unittest.main()

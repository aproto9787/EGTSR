"""Tests for Step 09: Release Cutover / Rollback.

Covers:
- Staged cutover (baseline → A → B → C → D)
- One-switch rollback (full/medium/minimal)
- Rollback from any stage
- Cutover state persistence and history
- Release checklist automation
- CLI wiring for cutover/rollback/release commands
- Runtime flag file consistency after cutover/rollback
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from egtsr_runtime.compat.cutover import (
    CutoverManager,
    CutoverState,
    _STAGE_FLAGS,
    _STAGE_ORDER,
)
from egtsr_runtime.compat.release_check import ReleaseChecker, save_release_report
from egtsr_runtime.config import RuntimeConfig, apply_overrides


class TestCutoverStageDefinitions(unittest.TestCase):
    """Verify stage flag configurations match document 11."""

    def test_baseline_is_legacy(self) -> None:
        flags = _STAGE_FLAGS["baseline"]
        self.assertEqual(flags["runtime_mode"], "legacy")
        self.assertFalse(flags["enable_daemon"])
        self.assertFalse(flags["enable_incremental_compile"])
        self.assertFalse(flags["enable_projection_tables"])
        self.assertFalse(flags["enable_reverse_index"])

    def test_stage_a_daemon_only(self) -> None:
        """Stage A: daemon on, projection off, compiler full."""
        flags = _STAGE_FLAGS["A"]
        self.assertEqual(flags["runtime_mode"], "daemon")
        self.assertTrue(flags["enable_daemon"])
        self.assertFalse(flags["enable_incremental_compile"])
        self.assertFalse(flags["enable_projection_tables"])
        self.assertTrue(flags["enable_reverse_index"])

    def test_stage_b_projection_shadow(self) -> None:
        """Stage B: daemon on, projection shadow, compiler full."""
        flags = _STAGE_FLAGS["B"]
        self.assertEqual(flags["runtime_mode"], "daemon")
        self.assertTrue(flags["enable_daemon"])
        self.assertFalse(flags["enable_incremental_compile"])
        self.assertTrue(flags["enable_projection_tables"])

    def test_stage_c_dual_run(self) -> None:
        """Stage C: shadow mode — dual-run compiler."""
        flags = _STAGE_FLAGS["C"]
        self.assertEqual(flags["runtime_mode"], "shadow")
        self.assertTrue(flags["enable_daemon"])
        self.assertTrue(flags["enable_incremental_compile"])
        self.assertTrue(flags["enable_projection_tables"])

    def test_stage_d_incremental_primary(self) -> None:
        """Stage D: daemon mode — incremental as primary."""
        flags = _STAGE_FLAGS["D"]
        self.assertEqual(flags["runtime_mode"], "daemon")
        self.assertTrue(flags["enable_daemon"])
        self.assertTrue(flags["enable_incremental_compile"])
        self.assertTrue(flags["enable_projection_tables"])

    def test_stage_order(self) -> None:
        self.assertEqual(_STAGE_ORDER, ["baseline", "A", "B", "C", "D"])


class TestCutoverManager(unittest.TestCase):
    """Test CutoverManager state transitions."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.egtsr_dir = self.tmp.name
        self.mgr = CutoverManager(self.egtsr_dir)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_initial_status_is_baseline(self) -> None:
        state = self.mgr.status()
        self.assertEqual(state.current_stage, "baseline")
        self.assertEqual(len(state.history), 0)

    def test_advance_baseline_to_a(self) -> None:
        state = self.mgr.advance()
        self.assertEqual(state.current_stage, "A")
        self.assertEqual(len(state.history), 1)
        self.assertEqual(state.history[0].action, "advance")
        self.assertEqual(state.history[0].from_stage, "baseline")
        self.assertEqual(state.history[0].to_stage, "A")

    def test_advance_full_sequence(self) -> None:
        """Advance through all stages: baseline → A → B → C → D."""
        for expected in ["A", "B", "C", "D"]:
            state = self.mgr.advance()
            self.assertEqual(state.current_stage, expected)

    def test_advance_past_d_raises(self) -> None:
        for _ in range(4):
            self.mgr.advance()
        with self.assertRaises(ValueError):
            self.mgr.advance()

    def test_set_stage_directly(self) -> None:
        state = self.mgr.set_stage("C")
        self.assertEqual(state.current_stage, "C")
        self.assertEqual(state.history[0].action, "set")

    def test_set_invalid_stage_raises(self) -> None:
        with self.assertRaises(ValueError):
            self.mgr.set_stage("X")  # type: ignore[arg-type]

    def test_set_same_stage_noop(self) -> None:
        state = self.mgr.set_stage("baseline")
        self.assertEqual(len(state.history), 0)

    def test_flags_file_written_on_advance(self) -> None:
        """runtime_flags.json is updated when advancing."""
        self.mgr.advance()  # → A
        flags_path = Path(self.egtsr_dir) / "runtime_flags.json"
        self.assertTrue(flags_path.is_file())
        data = json.loads(flags_path.read_text())
        self.assertEqual(data["runtime_mode"], "daemon")
        self.assertTrue(data["enable_daemon"])
        self.assertFalse(data["enable_incremental_compile"])

    def test_state_persists_across_instances(self) -> None:
        self.mgr.advance()  # → A
        self.mgr.advance()  # → B
        mgr2 = CutoverManager(self.egtsr_dir)
        state = mgr2.status()
        self.assertEqual(state.current_stage, "B")
        self.assertEqual(len(state.history), 2)

    def test_stage_flags_returns_correct_config(self) -> None:
        for stage in _STAGE_ORDER:
            flags = self.mgr.stage_flags(stage)
            self.assertIn("runtime_mode", flags)
            self.assertIn("enable_daemon", flags)


class TestRollback(unittest.TestCase):
    """Test one-switch rollback from various stages."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.egtsr_dir = self.tmp.name
        self.mgr = CutoverManager(self.egtsr_dir)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_full_rollback_from_d(self) -> None:
        """Full rollback from stage D → baseline."""
        self.mgr.set_stage("D")
        state = self.mgr.rollback(level="full")
        self.assertEqual(state.current_stage, "baseline")

        # Verify flags file
        flags = json.loads(
            (Path(self.egtsr_dir) / "runtime_flags.json").read_text()
        )
        self.assertEqual(flags["runtime_mode"], "legacy")
        self.assertFalse(flags["enable_daemon"])
        self.assertFalse(flags["enable_incremental_compile"])
        self.assertFalse(flags["enable_projection_tables"])
        self.assertFalse(flags["enable_reverse_index"])

    def test_minimal_rollback_resets_compiler_only(self) -> None:
        self.mgr.set_stage("D")
        state = self.mgr.rollback(level="minimal")
        self.assertEqual(state.current_stage, "baseline")

        flags = json.loads(
            (Path(self.egtsr_dir) / "runtime_flags.json").read_text()
        )
        # minimal: only compiler reset — runtime_mode stays daemon from D
        self.assertEqual(flags["runtime_mode"], "daemon")
        self.assertTrue(flags["enable_daemon"])
        self.assertFalse(flags["enable_incremental_compile"])
        # projection unchanged from D
        self.assertTrue(flags["enable_projection_tables"])

    def test_medium_rollback_resets_compiler_and_projection(self) -> None:
        self.mgr.set_stage("D")
        state = self.mgr.rollback(level="medium")
        self.assertEqual(state.current_stage, "baseline")

        flags = json.loads(
            (Path(self.egtsr_dir) / "runtime_flags.json").read_text()
        )
        self.assertEqual(flags["runtime_mode"], "daemon")
        self.assertFalse(flags["enable_incremental_compile"])
        self.assertFalse(flags["enable_projection_tables"])

    def test_rollback_from_every_stage(self) -> None:
        """Rollback should work from any stage."""
        for stage in ["A", "B", "C", "D"]:
            mgr = CutoverManager(self.egtsr_dir)
            mgr.set_stage(stage)
            state = mgr.rollback(level="full")
            self.assertEqual(state.current_stage, "baseline")

    def test_rollback_records_history(self) -> None:
        self.mgr.set_stage("C")
        state = self.mgr.rollback(level="full")
        rollback_entry = state.history[-1]
        self.assertEqual(rollback_entry.action, "rollback")
        self.assertEqual(rollback_entry.from_stage, "C")
        self.assertEqual(rollback_entry.to_stage, "baseline")
        self.assertIn("full", rollback_entry.detail)

    def test_rollback_then_re_advance(self) -> None:
        """After rollback, cutover can restart from baseline."""
        self.mgr.set_stage("D")
        self.mgr.rollback(level="full")
        state = self.mgr.advance()
        self.assertEqual(state.current_stage, "A")


class TestRollbackFlagsMatchApplyOverrides(unittest.TestCase):
    """Verify that rollback flags are honored by apply_overrides."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.egtsr_dir = self.tmp.name

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_full_rollback_produces_legacy_config(self) -> None:
        mgr = CutoverManager(self.egtsr_dir)
        mgr.set_stage("D")
        mgr.rollback(level="full")

        config = RuntimeConfig(
            repo_root="/r",
            egtsr_dir=self.egtsr_dir,
            db_path="/r/.egtsr/session.db",
        )
        config = apply_overrides(config)
        self.assertEqual(config.runtime_mode, "legacy")
        self.assertFalse(config.enable_daemon)
        self.assertFalse(config.enable_incremental_compile)

    def test_advance_to_d_produces_daemon_config(self) -> None:
        mgr = CutoverManager(self.egtsr_dir)
        mgr.set_stage("D")

        config = RuntimeConfig(
            repo_root="/r",
            egtsr_dir=self.egtsr_dir,
            db_path="/r/.egtsr/session.db",
        )
        config = apply_overrides(config)
        self.assertEqual(config.runtime_mode, "daemon")
        self.assertTrue(config.enable_daemon)
        self.assertTrue(config.enable_incremental_compile)


class TestReleaseChecker(unittest.TestCase):
    """Test release checklist checks."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.egtsr_dir = self.tmp.name
        self.reports_dir = str(Path(self.egtsr_dir) / "reports")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_all_checks_pass_empty_state(self) -> None:
        """With no reports, most checks pass (no data = OK for shadow/fallback)."""
        checker = ReleaseChecker(self.egtsr_dir)
        report = checker.run_all()
        # regression_gate fails (no report), but others pass
        names = {c.name: c.passed for c in report.checks}
        self.assertFalse(names["regression_gate"])
        self.assertTrue(names["shadow_critical_diffs"])
        self.assertTrue(names["contract_validation"])
        self.assertTrue(names["daemon_fallback"])
        self.assertTrue(names["cutover_stage"])

    def test_regression_gate_pass_with_report(self) -> None:
        """Gate check passes when latest report has overall_pass=True."""
        rd = Path(self.reports_dir)
        rd.mkdir(parents=True, exist_ok=True)
        gate_data = {
            "overall_pass": True,
            "checks": [{"name": "latency.p95_absolute", "passed": True}],
        }
        (rd / "gate_2026-01-01T00-00-00.json").write_text(
            json.dumps(gate_data), encoding="utf-8"
        )
        checker = ReleaseChecker(self.egtsr_dir)
        report = checker.run_all()
        gate = next(c for c in report.checks if c.name == "regression_gate")
        self.assertTrue(gate.passed)

    def test_regression_gate_fail_with_failed_report(self) -> None:
        rd = Path(self.reports_dir)
        rd.mkdir(parents=True, exist_ok=True)
        gate_data = {
            "overall_pass": False,
            "checks": [
                {"name": "latency.p95_absolute", "passed": False},
            ],
        }
        (rd / "gate_2026-01-01T00-00-00.json").write_text(
            json.dumps(gate_data), encoding="utf-8"
        )
        checker = ReleaseChecker(self.egtsr_dir)
        report = checker.run_all()
        gate = next(c for c in report.checks if c.name == "regression_gate")
        self.assertFalse(gate.passed)

    def test_shadow_critical_diff_detected(self) -> None:
        shadow_dir = Path(self.reports_dir) / "shadow"
        shadow_dir.mkdir(parents=True, exist_ok=True)
        diff_data = {
            "compile": {"has_critical_diff": True, "critical_diffs": [{}]},
        }
        (shadow_dir / "shadow_diff_test_001.json").write_text(
            json.dumps(diff_data), encoding="utf-8"
        )
        checker = ReleaseChecker(self.egtsr_dir)
        report = checker.run_all()
        shadow = next(c for c in report.checks if c.name == "shadow_critical_diffs")
        self.assertFalse(shadow.passed)

    def test_daemon_fallback_rate_high(self) -> None:
        metrics_dir = Path(self.egtsr_dir) / "metrics"
        metrics_dir.mkdir(parents=True, exist_ok=True)
        # 10 events, 2 fallbacks = 20% > 5%
        lines = []
        for i in range(10):
            entry = {"event": "hook_complete", "daemon_fallback": i < 2}
            lines.append(json.dumps(entry))
        (metrics_dir / "metrics.jsonl").write_text(
            "\n".join(lines), encoding="utf-8"
        )
        checker = ReleaseChecker(self.egtsr_dir)
        report = checker.run_all()
        fb = next(c for c in report.checks if c.name == "daemon_fallback")
        self.assertFalse(fb.passed)

    def test_daemon_fallback_rate_ok(self) -> None:
        metrics_dir = Path(self.egtsr_dir) / "metrics"
        metrics_dir.mkdir(parents=True, exist_ok=True)
        lines = []
        for _ in range(100):
            entry = {"event": "hook_complete", "daemon_fallback": False}
            lines.append(json.dumps(entry))
        (metrics_dir / "metrics.jsonl").write_text(
            "\n".join(lines), encoding="utf-8"
        )
        checker = ReleaseChecker(self.egtsr_dir)
        report = checker.run_all()
        fb = next(c for c in report.checks if c.name == "daemon_fallback")
        self.assertTrue(fb.passed)

    def test_save_release_report(self) -> None:
        checker = ReleaseChecker(self.egtsr_dir)
        report = checker.run_all()
        rd = Path(self.reports_dir)
        rd.mkdir(parents=True, exist_ok=True)
        path = save_release_report(report, str(rd))
        self.assertTrue(Path(path).is_file())
        data = json.loads(Path(path).read_text())
        self.assertIn("overall_pass", data)
        self.assertIn("checks", data)


class TestCLIWiring(unittest.TestCase):
    """Test CLI argument parsing and dispatch for cutover/rollback/release."""

    def test_cutover_status_parses(self) -> None:
        from egtsr_runtime.cli.main import build_parser

        parser = build_parser()
        args = parser.parse_args(["cutover", "status"])
        self.assertEqual(args.command, "cutover")
        self.assertEqual(args.cutover_action, "status")

    def test_cutover_advance_parses(self) -> None:
        from egtsr_runtime.cli.main import build_parser

        parser = build_parser()
        args = parser.parse_args(["cutover", "advance"])
        self.assertEqual(args.cutover_action, "advance")

    def test_cutover_set_parses(self) -> None:
        from egtsr_runtime.cli.main import build_parser

        parser = build_parser()
        args = parser.parse_args(["cutover", "set", "C"])
        self.assertEqual(args.cutover_action, "set")
        self.assertEqual(args.stage, "C")

    def test_rollback_parses_default_full(self) -> None:
        from egtsr_runtime.cli.main import build_parser

        parser = build_parser()
        args = parser.parse_args(["rollback"])
        self.assertEqual(args.command, "rollback")
        self.assertEqual(args.level, "full")

    def test_rollback_parses_minimal(self) -> None:
        from egtsr_runtime.cli.main import build_parser

        parser = build_parser()
        args = parser.parse_args(["rollback", "--level", "minimal"])
        self.assertEqual(args.level, "minimal")

    def test_release_check_parses(self) -> None:
        from egtsr_runtime.cli.main import build_parser

        parser = build_parser()
        args = parser.parse_args(["release", "check"])
        self.assertEqual(args.command, "release")
        self.assertEqual(args.release_action, "check")

    def test_release_check_save_report_flag(self) -> None:
        from egtsr_runtime.cli.main import build_parser

        parser = build_parser()
        args = parser.parse_args(["release", "check", "--save-report"])
        self.assertTrue(args.save_report)


class TestCutoverIntegration(unittest.TestCase):
    """Integration: cutover → rollback → re-advance cycle."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.egtsr_dir = self.tmp.name

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_full_cutover_rollback_cycle(self) -> None:
        """Full lifecycle: advance to D, rollback to baseline, advance again."""
        mgr = CutoverManager(self.egtsr_dir)

        # Advance through all stages
        for expected in ["A", "B", "C", "D"]:
            state = mgr.advance()
            self.assertEqual(state.current_stage, expected)

        # Verify D flags
        flags = json.loads(
            (Path(self.egtsr_dir) / "runtime_flags.json").read_text()
        )
        self.assertEqual(flags["runtime_mode"], "daemon")
        self.assertTrue(flags["enable_incremental_compile"])

        # Rollback
        state = mgr.rollback(level="full")
        self.assertEqual(state.current_stage, "baseline")

        # Verify rollback flags
        flags = json.loads(
            (Path(self.egtsr_dir) / "runtime_flags.json").read_text()
        )
        self.assertEqual(flags["runtime_mode"], "legacy")
        self.assertFalse(flags["enable_daemon"])

        # Re-advance
        state = mgr.advance()
        self.assertEqual(state.current_stage, "A")

        # Full history: 4 advances + 1 rollback + 1 re-advance = 6
        self.assertEqual(len(state.history), 6)

    def test_rollback_atomic_no_intermediate_state(self) -> None:
        """Rollback writes all flags in a single file update."""
        mgr = CutoverManager(self.egtsr_dir)
        mgr.set_stage("D")

        # Rollback — flags file should be consistent
        mgr.rollback(level="full")
        flags = json.loads(
            (Path(self.egtsr_dir) / "runtime_flags.json").read_text()
        )
        # All flags should be legacy-compatible
        self.assertEqual(flags["runtime_mode"], "legacy")
        self.assertFalse(flags["enable_daemon"])
        self.assertFalse(flags["enable_incremental_compile"])
        self.assertFalse(flags["enable_projection_tables"])
        self.assertFalse(flags["enable_reverse_index"])


if __name__ == "__main__":
    unittest.main()

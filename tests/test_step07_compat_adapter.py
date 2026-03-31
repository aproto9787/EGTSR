"""Tests for Step 07: Compatibility Adapter + Dual-Run Cutover.

Covers:
- Mode matrix flag propagation
- Shadow compile runner (dual-run + diff)
- Shadow invalidation runner (dual-run + diff)
- Contract validation helpers
- Shadow diff report writer
- Entrypoint apply_overrides integration
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from egtsr_runtime.config import RuntimeConfig, apply_overrides, is_shadow_mode


class TestModeMatrix(unittest.TestCase):
    """Mode matrix sets feature flags based on runtime_mode."""

    def _make_config(self, egtsr_dir: str = "/tmp/egtsr") -> RuntimeConfig:
        return RuntimeConfig(
            repo_root="/r", egtsr_dir=egtsr_dir, db_path="/r/.egtsr/session.db"
        )

    def test_legacy_mode_all_flags_off(self) -> None:
        from egtsr_runtime.compat.mode_matrix import apply_mode_matrix

        cfg = self._make_config()
        cfg.runtime_mode = "legacy"
        apply_mode_matrix(cfg)
        self.assertFalse(cfg.enable_daemon)
        self.assertFalse(cfg.enable_incremental_compile)
        self.assertFalse(cfg.enable_projection_tables)
        self.assertFalse(cfg.enable_reverse_index)

    def test_daemon_mode_all_flags_on(self) -> None:
        from egtsr_runtime.compat.mode_matrix import apply_mode_matrix

        cfg = self._make_config()
        cfg.runtime_mode = "daemon"
        apply_mode_matrix(cfg)
        self.assertTrue(cfg.enable_daemon)
        self.assertTrue(cfg.enable_incremental_compile)
        self.assertTrue(cfg.enable_projection_tables)
        self.assertTrue(cfg.enable_reverse_index)

    def test_shadow_mode_all_flags_on(self) -> None:
        from egtsr_runtime.compat.mode_matrix import apply_mode_matrix

        cfg = self._make_config()
        cfg.runtime_mode = "shadow"
        apply_mode_matrix(cfg)
        self.assertTrue(cfg.enable_daemon)
        self.assertTrue(cfg.enable_incremental_compile)
        self.assertTrue(cfg.enable_projection_tables)
        self.assertTrue(cfg.enable_reverse_index)

    def test_explicit_override_wins(self) -> None:
        """Explicit flag=False in env should override mode matrix default."""
        from egtsr_runtime.compat.mode_matrix import apply_mode_matrix

        cfg = self._make_config()
        cfg.runtime_mode = "daemon"
        cfg.enable_daemon = True  # already set by env override
        apply_mode_matrix(cfg)
        # Should not change — already True
        self.assertTrue(cfg.enable_daemon)


class TestModeMatrixViaApplyOverrides(unittest.TestCase):
    """Mode matrix integrates correctly with apply_overrides."""

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

    def test_daemon_mode_via_file_sets_flags(self) -> None:
        flags_path = Path(self.egtsr_dir) / "runtime_flags.json"
        flags_path.write_text(json.dumps({"runtime_mode": "daemon"}))
        cfg = apply_overrides(self._make_config())
        self.assertEqual(cfg.runtime_mode, "daemon")
        self.assertTrue(cfg.enable_daemon)
        self.assertTrue(cfg.enable_incremental_compile)

    def test_shadow_mode_via_env(self) -> None:
        self._set_env("EGTSR_RUNTIME_MODE", "shadow")
        cfg = apply_overrides(self._make_config())
        self.assertEqual(cfg.runtime_mode, "shadow")
        self.assertTrue(cfg.enable_daemon)
        self.assertTrue(cfg.enable_incremental_compile)

    def test_env_flag_override_beats_mode_matrix(self) -> None:
        """Explicit env override should beat mode matrix defaults."""
        flags_path = Path(self.egtsr_dir) / "runtime_flags.json"
        flags_path.write_text(json.dumps({"runtime_mode": "daemon"}))
        self._set_env("EGTSR_ENABLE_DAEMON", "false")
        cfg = apply_overrides(self._make_config())
        self.assertEqual(cfg.runtime_mode, "daemon")
        # Mode matrix set it True, but env override set it False
        self.assertFalse(cfg.enable_daemon)

    def test_file_flag_override_beats_mode_matrix(self) -> None:
        """Explicit file override should beat mode matrix defaults."""
        flags_path = Path(self.egtsr_dir) / "runtime_flags.json"
        flags_path.write_text(json.dumps({
            "runtime_mode": "daemon",
            "enable_incremental_compile": False,
        }))
        cfg = apply_overrides(self._make_config())
        self.assertEqual(cfg.runtime_mode, "daemon")
        self.assertFalse(cfg.enable_incremental_compile)


class TestIsShadowMode(unittest.TestCase):
    def test_shadow(self) -> None:
        cfg = RuntimeConfig(
            repo_root="/r", egtsr_dir="/r/.egtsr", db_path="/r/.egtsr/session.db",
            runtime_mode="shadow",
        )
        self.assertTrue(is_shadow_mode(cfg))

    def test_legacy(self) -> None:
        cfg = RuntimeConfig(
            repo_root="/r", egtsr_dir="/r/.egtsr", db_path="/r/.egtsr/session.db",
            runtime_mode="legacy",
        )
        self.assertFalse(is_shadow_mode(cfg))

    def test_daemon(self) -> None:
        cfg = RuntimeConfig(
            repo_root="/r", egtsr_dir="/r/.egtsr", db_path="/r/.egtsr/session.db",
            runtime_mode="daemon",
        )
        self.assertFalse(is_shadow_mode(cfg))


class TestContractValidation(unittest.TestCase):
    """Test external contract validators."""

    def test_valid_allow_response(self) -> None:
        from egtsr_runtime.compat.contract import validate_hook_response
        from egtsr_runtime.hooks.responses import build_allow_response

        resp = build_allow_response("user_prompt_submit", additional_context="ok")
        violations = validate_hook_response(resp)
        self.assertEqual(violations, [])

    def test_valid_block_response(self) -> None:
        from egtsr_runtime.compat.contract import validate_hook_response
        from egtsr_runtime.hooks.responses import build_block_response

        resp = build_block_response(reason="test", additional_context="ctx")
        violations = validate_hook_response(resp)
        self.assertEqual(violations, [])

    def test_invalid_response_missing_hso(self) -> None:
        from egtsr_runtime.compat.contract import validate_hook_response

        violations = validate_hook_response({"foo": "bar"})
        self.assertTrue(any("hookSpecificOutput" in v for v in violations))

    def test_capsule_snapshot_valid(self) -> None:
        from egtsr_runtime.compat.contract import validate_capsule_snapshot

        data = {"phase": "decision", "header_obligations": [], "obligation_blocks": []}
        self.assertEqual(validate_capsule_snapshot(data), [])

    def test_capsule_snapshot_invalid(self) -> None:
        from egtsr_runtime.compat.contract import validate_capsule_snapshot

        violations = validate_capsule_snapshot({"phase": "decision"})
        self.assertTrue(len(violations) > 0)

    def test_resume_gate_valid(self) -> None:
        from egtsr_runtime.compat.contract import validate_resume_gate_snapshot

        data = {"session_id": "s1", "edit_blocked": False}
        self.assertEqual(validate_resume_gate_snapshot(data), [])


class TestShadowDiffEntry(unittest.TestCase):
    def test_diff_entry_fields(self) -> None:
        from egtsr_runtime.compat.shadow_runner import ShadowDiffEntry

        entry = ShadowDiffEntry(
            field_name="audit_pass",
            legacy_value=True,
            incremental_value=False,
            is_critical=True,
        )
        self.assertEqual(entry.field_name, "audit_pass")
        self.assertTrue(entry.is_critical)


class TestShadowCompileRunner(unittest.TestCase):
    """Test shadow compile dual-run with a minimal DB setup."""

    def test_shadow_compile_no_obligations(self) -> None:
        """Shadow compile with empty session should produce no diffs."""
        from egtsr_runtime.compat.shadow_runner import ShadowCompileRunner

        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "test.db")
            from egtsr_runtime.db.uow import SqliteUnitOfWork

            config = RuntimeConfig(
                repo_root=tmp,
                egtsr_dir=tmp,
                db_path=db_path,
                runtime_mode="shadow",
                enable_incremental_compile=True,
                enable_projection_tables=True,
            )
            with SqliteUnitOfWork(db_path) as uow:
                runner = ShadowCompileRunner(uow, config)
                result = runner.compile("test-session")

                self.assertIsNotNone(result.legacy_capsule)
                self.assertFalse(result.has_critical_diff)
                self.assertIsNone(result.error)


class TestShadowCompileAllowBlockDiff(unittest.TestCase):
    """Verify that allow_block divergence is detected in shadow diff."""

    def test_allow_block_divergence_detected(self) -> None:
        from egtsr_runtime.compat.shadow_runner import ShadowCompileResult, ShadowCompileRunner
        from egtsr_runtime.compiler.audit import CapsuleAuditEngine
        from egtsr_runtime.compiler.decision_models import DecisionCapsuleV0

        # Legacy capsule: audit passes (allow)
        legacy = DecisionCapsuleV0(
            header_obligations=["obl-1"],
            obligation_blocks=[],
            audit_inputs={
                "open_obligation_ids": ["obl-1"],
                "rendered_obligation_ids": ["obl-1"],
                "stale_evidence_ids_seen": [],
                "unsupported_confirmed_assertion_ids": [],
                "live_stale_ticket_ids": [],
                "reopened_obligation_ids": [],
                "budget": 900,
            },
        )
        legacy.token_estimate = 100

        # Incremental capsule: audit FAILS (block) — missing rendered obligation
        incremental = DecisionCapsuleV0(
            header_obligations=["obl-1"],
            obligation_blocks=[],
            audit_inputs={
                "open_obligation_ids": ["obl-1"],
                "rendered_obligation_ids": [],  # missing → hard fail
                "stale_evidence_ids_seen": [],
                "unsupported_confirmed_assertion_ids": [],
                "live_stale_ticket_ids": [],
                "reopened_obligation_ids": [],
                "budget": 900,
            },
        )
        incremental.token_estimate = 100

        result = ShadowCompileResult(
            legacy_capsule=legacy,
            incremental_capsule=incremental,
        )

        # Manually invoke _diff via the runner's method
        runner_cls = ShadowCompileRunner.__new__(ShadowCompileRunner)
        runner_cls._audit_engine = CapsuleAuditEngine()
        runner_cls._diff(result, legacy, incremental)

        self.assertTrue(result.has_critical_diff)

        # allow_block diff should be present
        allow_block_diffs = [
            d for d in result.critical_diffs if d.field_name == "allow_block"
        ]
        self.assertEqual(len(allow_block_diffs), 1)
        self.assertEqual(allow_block_diffs[0].legacy_value, "allow")
        self.assertEqual(allow_block_diffs[0].incremental_value, "block")
        self.assertTrue(allow_block_diffs[0].is_critical)

    def test_allow_block_match_no_diff(self) -> None:
        from egtsr_runtime.compat.shadow_runner import ShadowCompileResult, ShadowCompileRunner
        from egtsr_runtime.compiler.audit import CapsuleAuditEngine
        from egtsr_runtime.compiler.decision_models import DecisionCapsuleV0

        # Both capsules: audit passes (allow)
        capsule = DecisionCapsuleV0(
            header_obligations=["obl-1"],
            obligation_blocks=[],
            audit_inputs={
                "open_obligation_ids": ["obl-1"],
                "rendered_obligation_ids": ["obl-1"],
                "stale_evidence_ids_seen": [],
                "unsupported_confirmed_assertion_ids": [],
                "live_stale_ticket_ids": [],
                "reopened_obligation_ids": [],
                "budget": 900,
            },
        )
        capsule.token_estimate = 100

        result = ShadowCompileResult(
            legacy_capsule=capsule,
            incremental_capsule=capsule,
        )

        runner_cls = ShadowCompileRunner.__new__(ShadowCompileRunner)
        runner_cls._audit_engine = CapsuleAuditEngine()
        runner_cls._diff(result, capsule, capsule)

        self.assertFalse(result.has_critical_diff)
        allow_block_diffs = [
            d for d in result.critical_diffs if d.field_name == "allow_block"
        ]
        self.assertEqual(len(allow_block_diffs), 0)


class TestShadowDiffReportWriter(unittest.TestCase):
    def test_write_report(self) -> None:
        from egtsr_runtime.compat.shadow_runner import (
            ShadowCompileResult,
            ShadowDiffEntry,
            write_shadow_diff_report,
        )
        from egtsr_runtime.compiler.decision_models import DecisionCapsuleV0

        with tempfile.TemporaryDirectory() as tmp:
            result = ShadowCompileResult(
                legacy_capsule=DecisionCapsuleV0(),
                incremental_capsule=DecisionCapsuleV0(),
                critical_diffs=[
                    ShadowDiffEntry(
                        field_name="audit_pass",
                        legacy_value=True,
                        incremental_value=False,
                        is_critical=True,
                    )
                ],
                has_critical_diff=True,
            )
            path = write_shadow_diff_report(
                tmp,
                hook_name="user_prompt_submit",
                session_id="s1",
                compile_result=result,
            )
            self.assertIsNotNone(path)
            shadow_dir = Path(tmp) / "shadow"
            self.assertTrue(shadow_dir.exists())

            report_files = list(shadow_dir.glob("shadow_diff_*.json"))
            self.assertEqual(len(report_files), 1)

            with report_files[0].open() as fh:
                data = json.load(fh)
            self.assertEqual(data["hook_name"], "user_prompt_submit")
            self.assertEqual(data["session_id"], "s1")
            self.assertTrue(data["compile"]["has_critical_diff"])
            self.assertEqual(len(data["compile"]["critical_diffs"]), 1)

    def test_no_report_when_no_data(self) -> None:
        from egtsr_runtime.compat.shadow_runner import write_shadow_diff_report

        with tempfile.TemporaryDirectory() as tmp:
            path = write_shadow_diff_report(
                tmp, hook_name="test", session_id="s1"
            )
            self.assertIsNone(path)


class TestShadowInvalidationRunner(unittest.TestCase):
    """Test shadow invalidation dual-run with empty session."""

    def test_shadow_invalidation_no_data(self) -> None:
        from egtsr_runtime.compat.shadow_runner import ShadowInvalidationRunner

        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "test.db")
            from egtsr_runtime.db.uow import SqliteUnitOfWork

            with SqliteUnitOfWork(db_path) as uow:
                runner = ShadowInvalidationRunner(uow)
                result = runner.apply("test-session", ["foo.py"])
                self.assertFalse(result.has_critical_diff)
                self.assertEqual(result.legacy_result.stale_assertion_ids, [])


if __name__ == "__main__":
    unittest.main()

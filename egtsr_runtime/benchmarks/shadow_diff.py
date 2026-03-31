"""Shadow-diff benchmark — compare legacy compile vs itself as a baseline.

In Step 00 there is no "new" compiler yet, so both sides run legacy.
This establishes the diff infrastructure for later steps where
a candidate (incremental) compiler will be plugged in.
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import asdict
from pathlib import Path

from egtsr_runtime.benchmarks.baseline import make_timestamp
from egtsr_runtime.benchmarks.diff_schema import CompileDiffResult, snapshot_from_capsule
from egtsr_runtime.benchmarks.scenarios import ForcedSplitScenario, StaleInjectionScenario
from egtsr_runtime.compiler import CapsuleAuditEngine, DecisionCapsuleCompiler, DecisionCompilerInput
from egtsr_runtime.db.uow import SqliteUnitOfWork


class ShadowDiffBenchmark:
    """Run the same scenario through two compile paths and compare."""

    def run(self, reports_dir: str | None = None) -> list[CompileDiffResult]:
        results: list[CompileDiffResult] = []

        with tempfile.TemporaryDirectory() as tmp_dir:
            for scenario_cls in (ForcedSplitScenario, StaleInjectionScenario):
                scenario = scenario_cls()
                db_path = str(Path(tmp_dir) / f"shadow_{scenario.name}.sqlite3")
                diff = self._run_dual(scenario, db_path)
                results.append(diff)

        if reports_dir:
            dir_path = Path(reports_dir)
            dir_path.mkdir(parents=True, exist_ok=True)
            ts = make_timestamp().replace(":", "-").replace(".", "-")
            payload = [self._diff_to_dict(d) for d in results]
            out_path = dir_path / f"shadow_diff_{ts}.json"
            with out_path.open("w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False)

        return results

    def _run_dual(self, scenario, db_path: str) -> CompileDiffResult:
        """Run scenario, compile with legacy twice (placeholder for future candidate)."""
        result = scenario.run(db_path)

        compiler = DecisionCapsuleCompiler()
        audit_engine = CapsuleAuditEngine()

        with SqliteUnitOfWork(db_path) as uow:
            session_id = f"bench-{scenario.name}"
            open_obligations = uow.obligations.list_open(session_id)
            evidence = uow.evidence.list_for_session(session_id)
            assertions = uow.assertions.list_for_session(session_id)
            invalidations = uow.invalidations.list_for_session(session_id)
            attempt_families = uow.attempt_families.list_for_session(session_id)

            compiler_input = DecisionCompilerInput(
                session_id=session_id,
                token_budget=900,
                open_obligations=open_obligations,
                evidence=evidence,
                assertions=assertions,
                invalidation_tickets=invalidations,
                attempt_families=attempt_families,
            )

            # Legacy path
            capsule_legacy = compiler.compile(compiler_input)
            audit_legacy = audit_engine.audit(capsule_legacy)
            snap_legacy = snapshot_from_capsule(capsule_legacy, audit_legacy, label="legacy")

            # Candidate path (same as legacy in Step 00 — placeholder)
            capsule_candidate = compiler.compile(compiler_input)
            audit_candidate = audit_engine.audit(capsule_candidate)
            snap_candidate = snapshot_from_capsule(capsule_candidate, audit_candidate, label="candidate")

        diff = CompileDiffResult(legacy=snap_legacy, candidate=snap_candidate)
        diff.compute()
        return diff

    @staticmethod
    def _diff_to_dict(diff: CompileDiffResult) -> dict:
        return {
            "legacy": {
                "path_label": diff.legacy.path_label,
                "token_estimate": diff.legacy.token_estimate,
                "obligation_count": diff.legacy.obligation_count,
                "audit_passed": diff.legacy.audit_passed,
            },
            "candidate": {
                "path_label": diff.candidate.path_label,
                "token_estimate": diff.candidate.token_estimate,
                "obligation_count": diff.candidate.obligation_count,
                "audit_passed": diff.candidate.audit_passed,
            },
            "token_delta": diff.token_delta,
            "audit_match": diff.audit_match,
            "block_count_match": diff.block_count_match,
            "hard_fail_match": diff.hard_fail_match,
            "rendered_text_identical": diff.rendered_text_identical,
        }

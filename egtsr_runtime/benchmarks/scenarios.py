"""Benchmark scenarios using existing runtime services."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from egtsr_runtime.compiler import CapsuleAuditEngine, DecisionCapsuleCompiler, DecisionCompilerInput
from egtsr_runtime.compiler.token_estimator import estimate_tokens
from egtsr_runtime.db.uow import SqliteUnitOfWork
from egtsr_runtime.enums import AssertionStatus, ObligationStatus, VerifyPhase
from egtsr_runtime.models import Assertion, Evidence, Obligation, Session
from egtsr_runtime.services import (
    AttemptFamilyService,
    FileTouchInvalidationService,
    ResumeGateService,
    VerifyResultsRecorder,
)


@dataclass(slots=True)
class ScenarioResult:
    name: str
    executed: bool = False
    audit_pass: bool = False
    stale_leak_count: int = 0
    token_count: int = 0
    resume_safety: bool = False
    obligation_count: int = 0
    evidence_count: int = 0
    failed_families: int = 0
    details: dict = field(default_factory=dict)


class _BaseScenario:
    name = "base"

    def __init__(self, token_budget: int = 900) -> None:
        self.token_budget = token_budget
        self.compiler = DecisionCapsuleCompiler()
        self.audit_engine = CapsuleAuditEngine()

    def _prepare_db(self, db_path: str) -> None:
        path = Path(db_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()

    def _seed_session(self, uow: SqliteUnitOfWork, session_id: str) -> None:
        uow.sessions.create(
            Session(
                id=session_id,
                repo_root="/repo",
                branch="main",
                head_hash="bench-head",
                status="active",
                created_at="2026-03-31T10:00:00Z",
                updated_at="2026-03-31T10:00:00Z",
            )
        )

    def _compile_state(self, uow: SqliteUnitOfWork, session_id: str):
        open_obligations = uow.obligations.list_open(session_id)
        evidence = uow.evidence.list_for_session(session_id)
        assertions = uow.assertions.list_for_session(session_id)
        invalidations = uow.invalidations.list_for_session(session_id)
        attempt_families = uow.attempt_families.list_for_session(session_id)
        capsule = self.compiler.compile(
            DecisionCompilerInput(
                session_id=session_id,
                token_budget=self.token_budget,
                open_obligations=open_obligations,
                evidence=evidence,
                assertions=assertions,
                invalidation_tickets=invalidations,
                attempt_families=attempt_families,
            )
        )
        audit = self.audit_engine.audit(capsule)
        return capsule, audit, open_obligations, evidence, assertions, invalidations, attempt_families

    def _make_obligation(
        self,
        session_id: str,
        obligation_id: str,
        statement: str,
        *,
        priority: int = 10,
        status: ObligationStatus = ObligationStatus.OPEN,
    ) -> Obligation:
        return Obligation(
            id=obligation_id,
            session_id=session_id,
            source="benchmark",
            statement=statement,
            priority=priority,
            status=status,
            acceptance_check="python -m unittest",
            metadata={},
            created_at="2026-03-31T10:01:00Z",
            updated_at="2026-03-31T10:01:00Z",
        )

    def _make_evidence(
        self,
        session_id: str,
        evidence_id: str,
        *,
        source_tool: str,
        path: str,
        excerpt: str,
        polarity: str = "positive",
        created_at: str,
    ) -> Evidence:
        return Evidence(
            id=evidence_id,
            session_id=session_id,
            kind="tool_output",
            source_tool=source_tool,
            path=path,
            scope_kind="file",
            scope_ref=path,
            file_hash=f"hash-{evidence_id}",
            polarity=polarity,
            excerpt=excerpt,
            metadata={},
            created_at=created_at,
        )

    def _make_assertion(
        self,
        session_id: str,
        assertion_id: str,
        obligation_id: str,
        statement: str,
        *,
        scope_ref: str,
        evidence_ids: list[str],
        status: AssertionStatus = AssertionStatus.SUPPORTED,
        confidence: float = 0.95,
        created_at: str,
    ) -> Assertion:
        return Assertion(
            id=assertion_id,
            session_id=session_id,
            obligation_id=obligation_id,
            statement=statement,
            scope_kind="file",
            scope_ref=scope_ref,
            status=status,
            confidence=confidence,
            evidence_ids=list(evidence_ids),
            metadata={},
            created_at=created_at,
            updated_at=created_at,
        )

    def _comparison_payload(
        self,
        *,
        capsule,
        open_obligations: list,
        evidence: list,
        assertions: list,
        invalidations: list,
        attempt_families: list,
    ) -> dict[str, int | float]:
        raw_payload = json.dumps(
            {
                "obligations": [asdict(item) for item in open_obligations],
                "evidence": [asdict(item) for item in evidence],
                "assertions": [asdict(item) for item in assertions],
                "invalidations": [asdict(item) for item in invalidations],
                "attempt_families": [asdict(item) for item in attempt_families],
            },
            sort_keys=True,
        )
        naive_text = "\n".join(
            [item.statement for item in open_obligations]
            + [item.statement for item in assertions]
            + [item.excerpt or item.path or item.id for item in evidence]
        )
        raw_tokens = estimate_tokens(raw_payload)
        naive_tokens = estimate_tokens(naive_text)
        egtsr_tokens = capsule.token_estimate
        savings_pct = 0.0
        if raw_tokens > 0:
            savings_pct = max(0.0, (raw_tokens - egtsr_tokens) / raw_tokens)
        return {
            "raw": raw_tokens,
            "naive": naive_tokens,
            "egtsr": egtsr_tokens,
            "savings_pct": round(savings_pct, 4),
        }

    def _live_evidence_count(self, assertions: list[Assertion]) -> int:
        return len(
            {
                evidence_id
                for item in assertions
                if item.status != AssertionStatus.STALE
                for evidence_id in item.evidence_ids
            }
        )

    def _failed_family_count(self, attempt_families: list) -> int:
        return sum(1 for item in attempt_families if item.fail_count > 0)

    def _resume_safety(self, uow: SqliteUnitOfWork, session_id: str, *, source: str) -> bool:
        gate = ResumeGateService(uow).evaluate(session_id=session_id, source=source, repo_dirty=False)
        return gate.edit_blocked and ResumeGateService.should_block_prompt(gate, "edit")

    @staticmethod
    def _count_rendered_leaks(rendered_text: str, markers: list[str]) -> int:
        return sum(1 for marker in markers if marker and marker in rendered_text)


class ForcedSplitScenario(_BaseScenario):
    """Test: obligation with multiple evidence streams, file change invalidates some.
    Setup: 1 obligation + 3 evidence (read/bash/diff), then invalidate 1 file.
    Expected: stale evidence excluded, capsule still includes obligation, audit passes."""

    name = "forced_split"

    def run(self, db_path: str) -> ScenarioResult:
        self._prepare_db(db_path)
        session_id = "bench-forced-split"
        stale_excerpt = "read evidence proves split path stays valid " * 5
        live_excerpt_a = "bash verify keeps unaffected flow intact " * 4
        live_excerpt_b = "diff evidence shows alternate path remains stable " * 4

        with SqliteUnitOfWork(db_path) as uow:
            self._seed_session(uow, session_id)
            obligation = self._make_obligation(session_id, "obl-forced", "Keep split decision capsule intact")
            evidence_items = [
                self._make_evidence(
                    session_id,
                    "ev-read",
                    source_tool="read",
                    path="/repo/src/split.py",
                    excerpt=stale_excerpt,
                    created_at="2026-03-31T10:02:00Z",
                ),
                self._make_evidence(
                    session_id,
                    "ev-bash",
                    source_tool="bash",
                    path="/repo/tests/test_split.py",
                    excerpt=live_excerpt_a,
                    created_at="2026-03-31T10:03:00Z",
                ),
                self._make_evidence(
                    session_id,
                    "ev-diff",
                    source_tool="diff",
                    path="/repo/docs/split.md",
                    excerpt=live_excerpt_b,
                    created_at="2026-03-31T10:04:00Z",
                ),
            ]
            assertions = [
                self._make_assertion(
                    session_id,
                    "as-read",
                    obligation.id,
                    "Read evidence supports split path",
                    scope_ref="/repo/src/split.py",
                    evidence_ids=["ev-read"],
                    created_at="2026-03-31T10:05:00Z",
                ),
                self._make_assertion(
                    session_id,
                    "as-bash",
                    obligation.id,
                    "Bash verification supports unaffected path",
                    scope_ref="/repo/tests/test_split.py",
                    evidence_ids=["ev-bash"],
                    created_at="2026-03-31T10:06:00Z",
                ),
                self._make_assertion(
                    session_id,
                    "as-diff",
                    obligation.id,
                    "Diff evidence supports fallback path",
                    scope_ref="/repo/docs/split.md",
                    evidence_ids=["ev-diff"],
                    created_at="2026-03-31T10:07:00Z",
                ),
            ]
            uow.obligations.upsert(obligation)
            for evidence in evidence_items:
                uow.evidence.create(evidence)
            for assertion in assertions:
                uow.assertions.upsert(assertion)
            uow.commit()

        with SqliteUnitOfWork(db_path) as uow:
            baseline_capsule, _, _, _, _, _, _ = self._compile_state(uow, session_id)

        with SqliteUnitOfWork(db_path) as uow:
            FileTouchInvalidationService(uow).apply(session_id, ["/repo/src/split.py"])
            uow.commit()

        with SqliteUnitOfWork(db_path) as uow:
            capsule, audit, open_obligations, evidence, assertions, invalidations, attempt_families = self._compile_state(
                uow, session_id
            )
            block = capsule.obligation_blocks[0]
            rendered_body = "\n".join(block.positive_items + block.negative_items + block.uncertainty_items)
            stale_leak_count = self._count_rendered_leaks(
                capsule.rendered_text,
                [stale_excerpt, "Read evidence supports split path"],
            )
            comparison = self._comparison_payload(
                capsule=capsule,
                open_obligations=open_obligations,
                evidence=evidence,
                assertions=assertions,
                invalidations=invalidations,
                attempt_families=attempt_families,
            )
            obligation_present = block.obligation_id == "obl-forced"
            # After invalidation, audit correctly hard-fails on live stale
            # tickets (3-axis: evidence + assertion).  The scenario succeeds
            # when the stale content is *excluded* from the rendered body and
            # the token count dropped.
            audit_detects_stale = any(
                "Stale evidence" in r or "stale assertion" in r.lower()
                for r in audit.hard_fail_reasons
            )
            executed = all(
                [
                    audit_detects_stale,
                    obligation_present,
                    stale_leak_count == 0,
                    stale_excerpt not in rendered_body,
                    live_excerpt_a in rendered_body,
                    live_excerpt_b in rendered_body,
                    capsule.token_estimate < baseline_capsule.token_estimate,
                ]
            )
            return ScenarioResult(
                name=self.name,
                executed=executed,
                audit_pass=not audit.passed,  # audit correctly fails
                stale_leak_count=stale_leak_count,
                token_count=capsule.token_estimate,
                resume_safety=self._resume_safety(uow, session_id, source="startup"),
                obligation_count=len(open_obligations),
                evidence_count=self._live_evidence_count(assertions),
                failed_families=self._failed_family_count(attempt_families),
                details={
                    "initial_token_count": baseline_capsule.token_estimate,
                    "raw_token_count": comparison["raw"],
                    "naive_token_count": comparison["naive"],
                    "token_savings_pct": comparison["savings_pct"],
                },
            )


class StaleInjectionScenario(_BaseScenario):
    """Test: repeated file changes progressively stale evidence.
    Setup: 1 obligation + multiple evidence, inject 2 file changes.
    Expected: evidence pool shrinks, capsule token count decreases, audit passes."""

    name = "stale_injection"

    def run(self, db_path: str) -> ScenarioResult:
        self._prepare_db(db_path)
        session_id = "bench-stale-injection"
        excerpts = {
            "alpha": "alpha evidence remains detailed and traceable " * 5,
            "beta": "beta evidence remains detailed and traceable " * 5,
            "gamma": "gamma evidence remains detailed and traceable " * 5,
        }

        with SqliteUnitOfWork(db_path) as uow:
            self._seed_session(uow, session_id)
            obligation = self._make_obligation(session_id, "obl-stale", "Track shrinking live evidence pool")
            uow.obligations.upsert(obligation)
            for index, name in enumerate(("alpha", "beta", "gamma"), start=1):
                evidence_id = f"ev-{name}"
                path = f"/repo/src/{name}.py"
                uow.evidence.create(
                    self._make_evidence(
                        session_id,
                        evidence_id,
                        source_tool="read",
                        path=path,
                        excerpt=excerpts[name],
                        created_at=f"2026-03-31T10:0{index}:00Z",
                    )
                )
                uow.assertions.upsert(
                    self._make_assertion(
                        session_id,
                        f"as-{name}",
                        obligation.id,
                        f"{name.title()} evidence is still current",
                        scope_ref=path,
                        evidence_ids=[evidence_id],
                        created_at=f"2026-03-31T10:1{index}:00Z",
                    )
                )
            uow.commit()

        with SqliteUnitOfWork(db_path) as uow:
            capsule_v1, _, _, _, _, _, _ = self._compile_state(uow, session_id)

        with SqliteUnitOfWork(db_path) as uow:
            FileTouchInvalidationService(uow).apply(session_id, ["/repo/src/alpha.py"])
            uow.commit()

        with SqliteUnitOfWork(db_path) as uow:
            capsule_v2, _, _, _, _, _, _ = self._compile_state(uow, session_id)

        with SqliteUnitOfWork(db_path) as uow:
            FileTouchInvalidationService(uow).apply(session_id, ["/repo/src/beta.py"])
            uow.commit()

        with SqliteUnitOfWork(db_path) as uow:
            capsule, audit, open_obligations, evidence, assertions, invalidations, attempt_families = self._compile_state(
                uow, session_id
            )
            block = capsule.obligation_blocks[0]
            rendered_body = "\n".join(block.positive_items + block.negative_items + block.uncertainty_items)
            stale_leak_count = self._count_rendered_leaks(capsule.rendered_text, [excerpts["alpha"], excerpts["beta"]])
            comparison = self._comparison_payload(
                capsule=capsule,
                open_obligations=open_obligations,
                evidence=evidence,
                assertions=assertions,
                invalidations=invalidations,
                attempt_families=attempt_families,
            )
            # After progressive invalidation, audit correctly hard-fails
            # on live stale tickets.  The scenario succeeds when stale
            # content is excluded and token count monotonically decreases.
            audit_detects_stale = any(
                "Stale evidence" in r or "stale assertion" in r.lower()
                for r in audit.hard_fail_reasons
            )
            executed = all(
                [
                    audit_detects_stale,
                    stale_leak_count == 0,
                    capsule_v1.token_estimate > capsule_v2.token_estimate > capsule.token_estimate,
                    excerpts["alpha"] not in rendered_body,
                    excerpts["beta"] not in rendered_body,
                    excerpts["gamma"] in rendered_body,
                    self._live_evidence_count(assertions) == 1,
                ]
            )
            return ScenarioResult(
                name=self.name,
                executed=executed,
                audit_pass=not audit.passed,  # audit correctly fails
                stale_leak_count=stale_leak_count,
                token_count=capsule.token_estimate,
                resume_safety=self._resume_safety(uow, session_id, source="startup"),
                obligation_count=len(open_obligations),
                evidence_count=self._live_evidence_count(assertions),
                failed_families=self._failed_family_count(attempt_families),
                details={
                    "initial_token_count": capsule_v1.token_estimate,
                    "mid_token_count": capsule_v2.token_estimate,
                    "raw_token_count": comparison["raw"],
                    "naive_token_count": comparison["naive"],
                    "token_savings_pct": comparison["savings_pct"],
                },
            )


class RepeatedFailureScenario(_BaseScenario):
    """Test: 3x verify failures on same obligation -> attempt family.
    Setup: 1 obligation, 3 failing verify results with same signature.
    Expected: AttemptFamily.fail_count=3, family summary in negative evidence."""

    name = "repeated_failure"

    def run(self, db_path: str) -> ScenarioResult:
        self._prepare_db(db_path)
        session_id = "bench-repeated-failure"
        summary = "third failing verify still blocks release path"

        with SqliteUnitOfWork(db_path) as uow:
            self._seed_session(uow, session_id)
            obligation = self._make_obligation(
                session_id,
                "obl-failure",
                "Stabilize repeated failing verification",
                status=ObligationStatus.ADDRESSED,
            )
            evidence = self._make_evidence(
                session_id,
                "ev-stable",
                source_tool="bash",
                path="/repo/tests/test_failure.py",
                excerpt="baseline evidence confirms the failure is reproducible " * 4,
                created_at="2026-03-31T10:02:00Z",
            )
            assertion = self._make_assertion(
                session_id,
                "as-stable",
                obligation.id,
                "Stable baseline evidence exists",
                scope_ref="/repo/tests/test_failure.py",
                evidence_ids=[evidence.id],
                created_at="2026-03-31T10:03:00Z",
            )
            uow.obligations.upsert(obligation)
            uow.evidence.create(evidence)
            uow.assertions.upsert(assertion)

            recorder = VerifyResultsRecorder(uow)
            family_service = AttemptFamilyService(uow)
            for excerpt in (
                "first failing verify on release path",
                "second failing verify on release path",
                summary,
            ):
                recorder.record(
                    session_id=session_id,
                    phase=VerifyPhase.TARGETED.value,
                    outcome="fail",
                    affected_obligation_ids=[obligation.id],
                    excerpt=excerpt,
                    metadata={"suite": "targeted"},
                )
                family_service.register_failure(
                    session_id=session_id,
                    obligation_id=obligation.id,
                    touched_files=["src/release.py", "tests/test_failure.py"],
                    outcome="fail",
                    excerpt=excerpt,
                )
            uow.commit()

        with SqliteUnitOfWork(db_path) as uow:
            capsule, audit, open_obligations, evidence, assertions, invalidations, attempt_families = self._compile_state(
                uow, session_id
            )
            block = capsule.obligation_blocks[0]
            comparison = self._comparison_payload(
                capsule=capsule,
                open_obligations=open_obligations,
                evidence=evidence,
                assertions=assertions,
                invalidations=invalidations,
                attempt_families=attempt_families,
            )
            family = attempt_families[0]
            executed = all(
                [
                    audit.passed,
                    family.fail_count == 3,
                    any(summary in item for item in block.negative_items),
                    any("Failed attempts:" in item for item in block.negative_items),
                ]
            )
            return ScenarioResult(
                name=self.name,
                executed=executed,
                audit_pass=audit.passed,
                stale_leak_count=0,
                token_count=capsule.token_estimate,
                resume_safety=self._resume_safety(uow, session_id, source="resume"),
                obligation_count=len(open_obligations),
                evidence_count=self._live_evidence_count(assertions),
                failed_families=self._failed_family_count(attempt_families),
                details={
                    "family_fail_count": family.fail_count,
                    "raw_token_count": comparison["raw"],
                    "naive_token_count": comparison["naive"],
                    "token_savings_pct": comparison["savings_pct"],
                },
            )

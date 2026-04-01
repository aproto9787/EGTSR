"""Tests for Phase 5: Invalidation/Audit 재정렬.

Covers:
- 3-axis invalidation (evidence → assertion → obligation)
- Propagation lineage (caused_by_ticket_id)
- Assertion supportability evaluation
- Audit hard-fail conditions for stale assertions and unreflected reopened obligations
"""
from __future__ import annotations

import tempfile
import unittest

from egtsr_runtime.compiler.audit import CapsuleAuditEngine
from egtsr_runtime.compiler.decision_compiler import DecisionCapsuleCompiler
from egtsr_runtime.compiler.decision_models import DecisionCompilerInput
from egtsr_runtime.config import RuntimeConfig
from egtsr_runtime.db.uow import SqliteUnitOfWork
from egtsr_runtime.enums import AssertionStatus, InvalidationStatus, ObligationStatus
from egtsr_runtime.models import Assertion, Evidence, InvalidationTicket, Obligation, Session
from egtsr_runtime.paths import ensure_runtime_dirs
from egtsr_runtime.services.invalidation import (
    FileTouchInvalidationService,
    evaluate_assertion_support,
)


class _BasePhase5Test(unittest.TestCase):
    """Shared setup for Phase 5 tests."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.paths = ensure_runtime_dirs(self.tmp_dir.name)
        self.config = RuntimeConfig(
            repo_root=self.paths.repo_root,
            egtsr_dir=self.paths.egtsr_dir,
            db_path=self.paths.db_path,
        )
        self.session_id = "sess-phase5"

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _seed_session(self, uow: SqliteUnitOfWork) -> None:
        if uow.sessions.get(self.session_id) is not None:
            return
        uow.sessions.create(
            Session(
                id=self.session_id,
                repo_root=self.paths.repo_root,
                branch="main",
                head_hash="abc123",
                status="active",
                created_at="2026-04-01T10:00:00Z",
                updated_at="2026-04-01T10:00:00Z",
            )
        )

    def _make_obligation(
        self, oid: str, status: ObligationStatus = ObligationStatus.OPEN
    ) -> Obligation:
        return Obligation(
            id=oid,
            session_id=self.session_id,
            source="test",
            statement=f"Obligation {oid}",
            priority=1,
            status=status,
            acceptance_check="pytest -q",
            metadata={},
            created_at="2026-04-01T10:01:00Z",
            updated_at="2026-04-01T10:01:00Z",
        )

    def _make_assertion(
        self,
        aid: str,
        obligation_id: str,
        *,
        scope_ref: str | None = None,
        status: AssertionStatus = AssertionStatus.SUPPORTED,
        evidence_ids: list[str] | None = None,
    ) -> Assertion:
        return Assertion(
            id=aid,
            session_id=self.session_id,
            obligation_id=obligation_id,
            statement=f"Assertion {aid}",
            scope_kind="file" if scope_ref else None,
            scope_ref=scope_ref,
            status=status,
            confidence=0.9,
            evidence_ids=evidence_ids or [],
            metadata={},
            created_at="2026-04-01T10:02:00Z",
            updated_at="2026-04-01T10:02:00Z",
        )

    def _make_evidence(
        self, eid: str, *, path: str, excerpt: str = "evidence excerpt"
    ) -> Evidence:
        return Evidence(
            id=eid,
            session_id=self.session_id,
            kind="read_span",
            source_tool="Read",
            path=path,
            scope_kind="file",
            scope_ref=path,
            polarity="positive",
            excerpt=excerpt,
            metadata={},
            created_at="2026-04-01T10:03:00Z",
        )

    def _svc(self, uow: SqliteUnitOfWork) -> FileTouchInvalidationService:
        return FileTouchInvalidationService(uow)


# ============================================================
# 3-axis invalidation + propagation lineage
# ============================================================


class TestThreeAxisInvalidation(_BasePhase5Test):
    """File touch creates evidence → assertion → obligation tickets with lineage."""

    def test_evidence_ticket_created_on_file_touch(self):
        """File touch creates a stale_evidence ticket."""
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            obl = self._make_obligation("obl-1")
            ev = self._make_evidence("ev-1", path="src/main.py")
            asrt = self._make_assertion("as-1", "obl-1", scope_ref="src/other.py", evidence_ids=["ev-1"])
            uow.obligations.upsert(obl)
            uow.evidence.create(ev)
            uow.assertions.upsert(asrt)

            result = self._svc(uow).apply(self.session_id, ["src/main.py"])
            uow.commit()

        self.assertIn("ev-1", result.stale_evidence_ids)
        self.assertIn("as-1", result.stale_assertion_ids)

    def test_propagation_lineage_evidence_to_assertion(self):
        """Assertion ticket's caused_by_ticket_id points to evidence ticket."""
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            obl = self._make_obligation("obl-1")
            ev = self._make_evidence("ev-1", path="src/main.py")
            # assertion's scope_ref is different, linked via evidence only
            asrt = self._make_assertion("as-1", "obl-1", scope_ref="src/other.py", evidence_ids=["ev-1"])
            uow.obligations.upsert(obl)
            uow.evidence.create(ev)
            uow.assertions.upsert(asrt)

            result = self._svc(uow).apply(self.session_id, ["src/main.py"])
            uow.commit()

        with SqliteUnitOfWork(self.config.db_path) as uow:
            tickets = uow.invalidations.list_for_session(self.session_id)

        evidence_tickets = [t for t in tickets if t.subject_type == "evidence"]
        assertion_tickets = [t for t in tickets if t.subject_type == "assertion"]

        self.assertEqual(len(evidence_tickets), 1)
        self.assertEqual(evidence_tickets[0].subject_id, "ev-1")
        self.assertIsNone(evidence_tickets[0].caused_by_ticket_id)

        self.assertEqual(len(assertion_tickets), 1)
        self.assertEqual(assertion_tickets[0].subject_id, "as-1")
        self.assertEqual(assertion_tickets[0].caused_by_ticket_id, evidence_tickets[0].id)

    def test_propagation_lineage_assertion_to_obligation(self):
        """Obligation ticket's caused_by_ticket_id points to assertion ticket."""
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            obl = self._make_obligation("obl-1", status=ObligationStatus.VERIFIED)
            ev = self._make_evidence("ev-1", path="src/main.py")
            asrt = self._make_assertion("as-1", "obl-1", scope_ref="src/main.py", evidence_ids=["ev-1"])
            uow.obligations.upsert(obl)
            uow.evidence.create(ev)
            uow.assertions.upsert(asrt)

            result = self._svc(uow).apply(self.session_id, ["src/main.py"])
            uow.commit()

        self.assertIn("obl-1", result.reopened_obligation_ids)

        with SqliteUnitOfWork(self.config.db_path) as uow:
            tickets = uow.invalidations.list_for_session(self.session_id)

        assertion_tickets = [t for t in tickets if t.subject_type == "assertion"]
        obligation_tickets = [t for t in tickets if t.subject_type == "obligation"]

        self.assertEqual(len(obligation_tickets), 1)
        self.assertEqual(obligation_tickets[0].subject_id, "obl-1")
        self.assertEqual(obligation_tickets[0].caused_by_ticket_id, assertion_tickets[0].id)

    def test_full_3_axis_chain(self):
        """Full chain: evidence → assertion → obligation with lineage."""
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            obl = self._make_obligation("obl-1", status=ObligationStatus.VERIFIED)
            ev = self._make_evidence("ev-1", path="src/module.py")
            asrt = self._make_assertion("as-1", "obl-1", scope_ref="src/other.py", evidence_ids=["ev-1"])
            uow.obligations.upsert(obl)
            uow.evidence.create(ev)
            uow.assertions.upsert(asrt)

            result = self._svc(uow).apply(self.session_id, ["src/module.py"])
            uow.commit()

        # All three axes should fire
        self.assertEqual(result.stale_evidence_ids, ["ev-1"])
        self.assertEqual(result.stale_assertion_ids, ["as-1"])
        self.assertEqual(result.reopened_obligation_ids, ["obl-1"])

        with SqliteUnitOfWork(self.config.db_path) as uow:
            tickets = uow.invalidations.list_for_session(self.session_id)

        by_type = {}
        for t in tickets:
            by_type.setdefault(t.subject_type, []).append(t)

        # evidence ticket: no parent
        self.assertEqual(len(by_type["evidence"]), 1)
        self.assertIsNone(by_type["evidence"][0].caused_by_ticket_id)

        # assertion ticket: caused by evidence ticket
        self.assertEqual(len(by_type["assertion"]), 1)
        self.assertEqual(by_type["assertion"][0].caused_by_ticket_id, by_type["evidence"][0].id)

        # obligation ticket: caused by assertion ticket
        self.assertEqual(len(by_type["obligation"]), 1)
        self.assertEqual(by_type["obligation"][0].caused_by_ticket_id, by_type["assertion"][0].id)

    def test_direct_scope_ref_match_no_evidence_lineage(self):
        """When assertion is staled by scope_ref match (not evidence), caused_by is None."""
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            obl = self._make_obligation("obl-1")
            asrt = self._make_assertion("as-1", "obl-1", scope_ref="src/main.py")
            uow.obligations.upsert(obl)
            uow.assertions.upsert(asrt)

            result = self._svc(uow).apply(self.session_id, ["src/main.py"])
            uow.commit()

        self.assertEqual(result.stale_assertion_ids, ["as-1"])
        self.assertEqual(result.stale_evidence_ids, [])

        with SqliteUnitOfWork(self.config.db_path) as uow:
            tickets = uow.invalidations.list_for_session(self.session_id)

        assertion_tickets = [t for t in tickets if t.subject_type == "assertion"]
        self.assertEqual(len(assertion_tickets), 1)
        self.assertIsNone(assertion_tickets[0].caused_by_ticket_id)

    def test_subject_type_enum_values(self):
        """All three subject_type values are used correctly."""
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            obl = self._make_obligation("obl-1", status=ObligationStatus.VERIFIED)
            ev = self._make_evidence("ev-1", path="src/target.py")
            asrt = self._make_assertion("as-1", "obl-1", scope_ref="src/other.py", evidence_ids=["ev-1"])
            uow.obligations.upsert(obl)
            uow.evidence.create(ev)
            uow.assertions.upsert(asrt)

            self._svc(uow).apply(self.session_id, ["src/target.py"])
            uow.commit()

        with SqliteUnitOfWork(self.config.db_path) as uow:
            tickets = uow.invalidations.list_for_session(self.session_id)

        subject_types = {t.subject_type for t in tickets}
        self.assertEqual(subject_types, {"evidence", "assertion", "obligation"})


# ============================================================
# Assertion supportability evaluation
# ============================================================


class TestAssertionSupportability(_BasePhase5Test):
    """evaluate_assertion_support returns correct supportability."""

    def test_supported_with_fresh_evidence(self):
        asrt = self._make_assertion("as-1", "obl-1", evidence_ids=["ev-1"])
        ev = self._make_evidence("ev-1", path="src/a.py")
        result = evaluate_assertion_support(asrt, {"ev-1": ev}, [])
        self.assertEqual(result, "supported")

    def test_unsupported_no_evidence(self):
        asrt = self._make_assertion("as-1", "obl-1", evidence_ids=[])
        result = evaluate_assertion_support(asrt, {}, [])
        self.assertEqual(result, "unsupported")

    def test_stale_by_status(self):
        asrt = self._make_assertion("as-1", "obl-1", status=AssertionStatus.STALE)
        result = evaluate_assertion_support(asrt, {}, [])
        self.assertEqual(result, "stale")

    def test_stale_by_assertion_ticket(self):
        asrt = self._make_assertion("as-1", "obl-1", evidence_ids=["ev-1"])
        ev = self._make_evidence("ev-1", path="src/a.py")
        ticket = InvalidationTicket(
            id="t-1",
            session_id=self.session_id,
            subject_type="assertion",
            subject_id="as-1",
            trigger_kind="file_touch",
            status=InvalidationStatus.LIVE,
        )
        result = evaluate_assertion_support(asrt, {"ev-1": ev}, [ticket])
        self.assertEqual(result, "stale")

    def test_stale_by_all_evidence_invalidated(self):
        asrt = self._make_assertion("as-1", "obl-1", evidence_ids=["ev-1"])
        ev = self._make_evidence("ev-1", path="src/a.py")
        ticket = InvalidationTicket(
            id="t-1",
            session_id=self.session_id,
            subject_type="evidence",
            subject_id="ev-1",
            trigger_kind="file_touch",
            status=InvalidationStatus.LIVE,
        )
        result = evaluate_assertion_support(asrt, {"ev-1": ev}, [ticket])
        self.assertEqual(result, "stale")

    def test_supported_with_some_fresh_evidence(self):
        """At least one fresh evidence → supported."""
        asrt = self._make_assertion("as-1", "obl-1", evidence_ids=["ev-1", "ev-2"])
        ev1 = self._make_evidence("ev-1", path="src/a.py")
        ev2 = self._make_evidence("ev-2", path="src/b.py")
        ticket = InvalidationTicket(
            id="t-1",
            session_id=self.session_id,
            subject_type="evidence",
            subject_id="ev-1",
            trigger_kind="file_touch",
            status=InvalidationStatus.LIVE,
        )
        result = evaluate_assertion_support(asrt, {"ev-1": ev1, "ev-2": ev2}, [ticket])
        self.assertEqual(result, "supported")

    def test_unsupported_speculative(self):
        asrt = self._make_assertion(
            "as-1", "obl-1", evidence_ids=["ev-1"], status=AssertionStatus.SPECULATIVE
        )
        ev = self._make_evidence("ev-1", path="src/a.py")
        result = evaluate_assertion_support(asrt, {"ev-1": ev}, [])
        self.assertEqual(result, "unsupported")

    def test_closed_ticket_does_not_affect(self):
        asrt = self._make_assertion("as-1", "obl-1", evidence_ids=["ev-1"])
        ev = self._make_evidence("ev-1", path="src/a.py")
        ticket = InvalidationTicket(
            id="t-1",
            session_id=self.session_id,
            subject_type="evidence",
            subject_id="ev-1",
            trigger_kind="file_touch",
            status=InvalidationStatus.CLOSED,
        )
        result = evaluate_assertion_support(asrt, {"ev-1": ev}, [ticket])
        self.assertEqual(result, "supported")

    def test_blocked_when_obligation_open(self):
        """Assertion is blocked when its linked obligation is not verified."""
        obl = self._make_obligation("obl-1", status=ObligationStatus.OPEN)
        asrt = self._make_assertion("as-1", "obl-1", evidence_ids=["ev-1"])
        ev = self._make_evidence("ev-1", path="src/a.py")
        result = evaluate_assertion_support(
            asrt, {"ev-1": ev}, [], obligations_by_id={"obl-1": obl}
        )
        self.assertEqual(result, "blocked")

    def test_blocked_when_obligation_addressed(self):
        """Addressed (not yet verified) obligation also blocks."""
        obl = self._make_obligation("obl-1", status=ObligationStatus.ADDRESSED)
        asrt = self._make_assertion("as-1", "obl-1", evidence_ids=["ev-1"])
        ev = self._make_evidence("ev-1", path="src/a.py")
        result = evaluate_assertion_support(
            asrt, {"ev-1": ev}, [], obligations_by_id={"obl-1": obl}
        )
        self.assertEqual(result, "blocked")

    def test_blocked_when_obligation_reopened(self):
        """Reopened obligation blocks its assertions."""
        obl = self._make_obligation("obl-1", status=ObligationStatus.REOPENED)
        asrt = self._make_assertion("as-1", "obl-1", evidence_ids=["ev-1"])
        ev = self._make_evidence("ev-1", path="src/a.py")
        result = evaluate_assertion_support(
            asrt, {"ev-1": ev}, [], obligations_by_id={"obl-1": obl}
        )
        self.assertEqual(result, "blocked")

    def test_not_blocked_when_obligation_verified(self):
        """Verified obligation does not block — returns supported."""
        obl = self._make_obligation("obl-1", status=ObligationStatus.VERIFIED)
        asrt = self._make_assertion("as-1", "obl-1", evidence_ids=["ev-1"])
        ev = self._make_evidence("ev-1", path="src/a.py")
        result = evaluate_assertion_support(
            asrt, {"ev-1": ev}, [], obligations_by_id={"obl-1": obl}
        )
        self.assertEqual(result, "supported")

    def test_stale_takes_priority_over_blocked(self):
        """Stale (highest priority) wins over blocked."""
        obl = self._make_obligation("obl-1", status=ObligationStatus.OPEN)
        asrt = self._make_assertion("as-1", "obl-1", status=AssertionStatus.STALE, evidence_ids=["ev-1"])
        ev = self._make_evidence("ev-1", path="src/a.py")
        result = evaluate_assertion_support(
            asrt, {"ev-1": ev}, [], obligations_by_id={"obl-1": obl}
        )
        self.assertEqual(result, "stale")

    def test_blocked_without_obligations_dict_returns_supported(self):
        """Without obligations_by_id, blocked check is skipped."""
        asrt = self._make_assertion("as-1", "obl-1", evidence_ids=["ev-1"])
        ev = self._make_evidence("ev-1", path="src/a.py")
        result = evaluate_assertion_support(asrt, {"ev-1": ev}, [])
        self.assertEqual(result, "supported")

    def test_blocked_no_obligation_id_returns_supported(self):
        """Assertion without obligation_id is not blocked."""
        obl = self._make_obligation("obl-1", status=ObligationStatus.OPEN)
        asrt = self._make_assertion("as-1", "obl-1", evidence_ids=["ev-1"])
        asrt.obligation_id = None  # detach
        ev = self._make_evidence("ev-1", path="src/a.py")
        result = evaluate_assertion_support(
            asrt, {"ev-1": ev}, [], obligations_by_id={"obl-1": obl}
        )
        self.assertEqual(result, "supported")


# ============================================================
# Compiler audit_inputs
# ============================================================


class TestCompilerAuditInputs(_BasePhase5Test):
    """DecisionCapsuleCompiler includes 3-axis stale IDs in audit_inputs."""

    def test_audit_inputs_contain_3_axis_ids(self):
        obl = self._make_obligation("obl-1", status=ObligationStatus.REOPENED)
        ev = self._make_evidence("ev-1", path="src/main.py")
        asrt = self._make_assertion(
            "as-1", "obl-1", scope_ref="src/main.py",
            evidence_ids=["ev-1"], status=AssertionStatus.SUPPORTED,
        )
        evidence_ticket = InvalidationTicket(
            id="t-ev-1",
            session_id=self.session_id,
            subject_type="evidence",
            subject_id="ev-1",
            trigger_kind="file_touch",
            status=InvalidationStatus.LIVE,
            created_at="2026-04-01T10:04:00Z",
            updated_at="2026-04-01T10:04:00Z",
        )
        assertion_ticket = InvalidationTicket(
            id="t-as-1",
            session_id=self.session_id,
            subject_type="assertion",
            subject_id="as-1",
            trigger_kind="file_touch",
            status=InvalidationStatus.LIVE,
            caused_by_ticket_id="t-ev-1",
            created_at="2026-04-01T10:04:01Z",
            updated_at="2026-04-01T10:04:01Z",
        )

        compiler = DecisionCapsuleCompiler()
        data = DecisionCompilerInput(
            session_id=self.session_id,
            token_budget=10000,
            open_obligations=[obl],
            evidence=[ev],
            assertions=[asrt],
            invalidation_tickets=[evidence_ticket, assertion_ticket],
            attempt_families=[],
        )
        capsule = compiler.compile(data)

        self.assertIn("live_stale_evidence_ids", capsule.audit_inputs)
        self.assertIn("live_stale_assertion_ids", capsule.audit_inputs)
        self.assertIn("live_reopened_obligation_ids", capsule.audit_inputs)

        self.assertEqual(capsule.audit_inputs["live_stale_evidence_ids"], ["ev-1"])
        self.assertEqual(capsule.audit_inputs["live_stale_assertion_ids"], ["as-1"])
        self.assertEqual(capsule.audit_inputs["live_reopened_obligation_ids"], ["obl-1"])


# ============================================================
# Audit hard-fail conditions
# ============================================================


class TestAuditHardFail(_BasePhase5Test):
    """CapsuleAuditEngine hard-fail conditions for stale axes."""

    def _make_capsule(self, **audit_overrides):
        from egtsr_runtime.compiler.decision_models import DecisionCapsuleV0, ObligationBlock

        defaults = {
            "open_obligation_ids": ["obl-1"],
            "rendered_obligation_ids": ["obl-1"],
            "stale_evidence_ids_seen": [],
            "live_stale_assertion_ids": [],
            "live_reopened_obligation_ids": [],
            "unsupported_confirmed_assertion_ids": [],
            "budget": 10000,
        }
        defaults.update(audit_overrides)
        return DecisionCapsuleV0(
            header_obligations=defaults["open_obligation_ids"],
            obligation_blocks=[
                ObligationBlock(
                    obligation_id=oid, priority=1, title=f"Obl {oid}", state="open"
                )
                for oid in defaults["rendered_obligation_ids"]
            ],
            token_estimate=100,
            audit_inputs=defaults,
        )

    def test_pass_when_clean(self):
        capsule = self._make_capsule()
        report = CapsuleAuditEngine().audit(capsule)
        self.assertTrue(report.passed)
        self.assertEqual(report.hard_fail_reasons, [])

    def test_hard_fail_stale_evidence(self):
        capsule = self._make_capsule(stale_evidence_ids_seen=["ev-1"])
        report = CapsuleAuditEngine().audit(capsule)
        self.assertFalse(report.passed)
        self.assertTrue(any("Stale evidence" in r for r in report.hard_fail_reasons))

    def test_hard_fail_stale_assertions(self):
        capsule = self._make_capsule(live_stale_assertion_ids=["as-1", "as-2"])
        report = CapsuleAuditEngine().audit(capsule)
        self.assertFalse(report.passed)
        self.assertTrue(any("stale assertions" in r.lower() for r in report.hard_fail_reasons))

    def test_hard_fail_unreflected_reopened_obligations(self):
        capsule = self._make_capsule(
            live_reopened_obligation_ids=["obl-2"],  # not in rendered
            rendered_obligation_ids=["obl-1"],
        )
        report = CapsuleAuditEngine().audit(capsule)
        self.assertFalse(report.passed)
        self.assertTrue(any("Reopened obligations not reflected" in r for r in report.hard_fail_reasons))

    def test_pass_when_reopened_is_rendered(self):
        capsule = self._make_capsule(
            live_reopened_obligation_ids=["obl-1"],
            rendered_obligation_ids=["obl-1"],
        )
        report = CapsuleAuditEngine().audit(capsule)
        # Should not fail on reopened — it is rendered
        reopened_failures = [r for r in report.hard_fail_reasons if "Reopened" in r]
        self.assertEqual(reopened_failures, [])

    def test_hard_fail_missing_obligation(self):
        capsule = self._make_capsule(
            open_obligation_ids=["obl-1", "obl-2"],
            rendered_obligation_ids=["obl-1"],
        )
        report = CapsuleAuditEngine().audit(capsule)
        self.assertFalse(report.passed)
        self.assertTrue(any("missing rendered" in r.lower() for r in report.hard_fail_reasons))

    def test_multiple_hard_fails(self):
        capsule = self._make_capsule(
            stale_evidence_ids_seen=["ev-1"],
            live_stale_assertion_ids=["as-1"],
            live_reopened_obligation_ids=["obl-missing"],
            rendered_obligation_ids=["obl-1"],
        )
        report = CapsuleAuditEngine().audit(capsule)
        self.assertFalse(report.passed)
        self.assertGreaterEqual(len(report.hard_fail_reasons), 3)


# ============================================================
# list_live_by_subject_type repository method
# ============================================================


class TestInvalidationRepositorySubjectType(_BasePhase5Test):
    """New list_live_by_subject_type repository method."""

    def test_list_live_by_subject_type(self):
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            obl = self._make_obligation("obl-1", status=ObligationStatus.VERIFIED)
            ev = self._make_evidence("ev-1", path="src/main.py")
            asrt = self._make_assertion("as-1", "obl-1", scope_ref="src/other.py", evidence_ids=["ev-1"])
            uow.obligations.upsert(obl)
            uow.evidence.create(ev)
            uow.assertions.upsert(asrt)

            self._svc(uow).apply(self.session_id, ["src/main.py"])
            uow.commit()

        with SqliteUnitOfWork(self.config.db_path) as uow:
            evidence_tickets = uow.invalidations.list_live_by_subject_type(self.session_id, "evidence")
            assertion_tickets = uow.invalidations.list_live_by_subject_type(self.session_id, "assertion")
            obligation_tickets = uow.invalidations.list_live_by_subject_type(self.session_id, "obligation")

        self.assertEqual(len(evidence_tickets), 1)
        self.assertEqual(evidence_tickets[0].subject_id, "ev-1")
        self.assertEqual(len(assertion_tickets), 1)
        self.assertEqual(assertion_tickets[0].subject_id, "as-1")
        self.assertEqual(len(obligation_tickets), 1)
        self.assertEqual(obligation_tickets[0].subject_id, "obl-1")


# ============================================================
# Regression: existing behavior unchanged
# ============================================================


class TestRegressionExistingBehavior(_BasePhase5Test):
    """Existing invalidation behavior must not regress."""

    def test_unrelated_file_no_op(self):
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            obl = self._make_obligation("obl-1")
            asrt = self._make_assertion("as-1", "obl-1", scope_ref="src/main.py")
            uow.obligations.upsert(obl)
            uow.assertions.upsert(asrt)

            result = self._svc(uow).apply(self.session_id, ["src/unrelated.py"])
            uow.commit()

        self.assertEqual(result.stale_evidence_ids, [])
        self.assertEqual(result.stale_assertion_ids, [])
        self.assertEqual(result.reopened_obligation_ids, [])
        self.assertEqual(result.invalidation_ticket_ids, [])

    def test_already_stale_not_restaled(self):
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            obl = self._make_obligation("obl-1")
            asrt = self._make_assertion(
                "as-1", "obl-1", scope_ref="src/main.py", status=AssertionStatus.STALE
            )
            uow.obligations.upsert(obl)
            uow.assertions.upsert(asrt)

            result = self._svc(uow).apply(self.session_id, ["src/main.py"])
            uow.commit()

        self.assertEqual(result.stale_assertion_ids, [])

    def test_empty_changed_files_no_op(self):
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            result = self._svc(uow).apply(self.session_id, [])
            uow.commit()

        self.assertEqual(result.stale_evidence_ids, [])
        self.assertEqual(result.stale_assertion_ids, [])

    def test_verified_obligation_reopened(self):
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            obl = self._make_obligation("obl-1", status=ObligationStatus.VERIFIED)
            asrt = self._make_assertion("as-1", "obl-1", scope_ref="src/main.py")
            uow.obligations.upsert(obl)
            uow.assertions.upsert(asrt)

            result = self._svc(uow).apply(self.session_id, ["src/main.py"])
            uow.commit()

        with SqliteUnitOfWork(self.config.db_path) as uow:
            stored = uow.obligations.get("obl-1")

        self.assertEqual(result.reopened_obligation_ids, ["obl-1"])
        self.assertEqual(stored.status, ObligationStatus.REOPENED)

    def test_open_obligation_not_reopened(self):
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            obl = self._make_obligation("obl-1", status=ObligationStatus.OPEN)
            asrt = self._make_assertion("as-1", "obl-1", scope_ref="src/main.py")
            uow.obligations.upsert(obl)
            uow.assertions.upsert(asrt)

            result = self._svc(uow).apply(self.session_id, ["src/main.py"])
            uow.commit()

        self.assertEqual(result.reopened_obligation_ids, [])


if __name__ == "__main__":
    unittest.main()

"""Shadow-diff tests: incremental vs legacy compiler critical field comparison.

Verifies that the incremental compiler path in UserPromptSubmitService
produces capsules with identical critical fields to the legacy path.
Fields compared per doc Section 8:
- allow/block (via audit_pass)
- audit_pass
- hard_fail_reasons
- open_obligation_ids
- rendered_obligation_ids
- live_stale_ticket_ids
- reopened_obligation_ids
- next_checks
"""
from __future__ import annotations

import json
import tempfile
import unittest

from egtsr_runtime.compiler import (
    CapsuleAuditEngine,
    DecisionCapsuleCompiler,
    DecisionCompilerInput,
)
from egtsr_runtime.compiler.incremental import IncrementalDecisionCompiler
from egtsr_runtime.config import RuntimeConfig
from egtsr_runtime.db.uow import SqliteUnitOfWork
from egtsr_runtime.enums import (
    AssertionStatus,
    InvalidationStatus,
    ObligationStatus,
)
from egtsr_runtime.hooks import UserPromptSubmitService, parse_hook_stdin
from egtsr_runtime.models import (
    Assertion,
    AttemptFamily,
    Evidence,
    InvalidationTicket,
    Obligation,
    Session,
)
from egtsr_runtime.paths import ensure_runtime_dirs
from egtsr_runtime.services.projections import (
    on_assertion_upsert,
    on_attempt_family_upsert,
    on_evidence_create,
    on_invalidation_upsert,
    on_obligation_upsert,
)

SESSION_ID = "sess-shadow"
TOKEN_BUDGET = 900


class TestShadowDiffCriticalFields(unittest.TestCase):
    """Dual-run compare: incremental vs legacy on critical fields."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.paths = ensure_runtime_dirs(self.tmp.name)
        self.config = RuntimeConfig(
            repo_root=self.paths.repo_root,
            egtsr_dir=self.paths.egtsr_dir,
            db_path=self.paths.db_path,
        )
        self.audit = CapsuleAuditEngine()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_allow_block_matches(self) -> None:
        """allow/block decision is identical between paths."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow)
            _seed_allow_state(uow)
            uow.commit()

            legacy_capsule = _legacy_compile(uow)
            inc_result = IncrementalDecisionCompiler(uow, TOKEN_BUDGET).compile(SESSION_ID)

        legacy_audit = self.audit.audit(legacy_capsule)
        inc_audit = self.audit.audit(inc_result.capsule)

        self.assertEqual(legacy_audit.passed, inc_audit.passed)
        self.assertTrue(legacy_audit.passed)
        self.assertTrue(inc_audit.passed)

    def test_block_decision_matches(self) -> None:
        """Both paths block on unsupported confirmed assertion."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow)
            _seed_block_state(uow)
            uow.commit()

            legacy_capsule = _legacy_compile(uow)
            inc_result = IncrementalDecisionCompiler(uow, TOKEN_BUDGET).compile(SESSION_ID)

        legacy_audit = self.audit.audit(legacy_capsule)
        inc_audit = self.audit.audit(inc_result.capsule)

        self.assertEqual(legacy_audit.passed, inc_audit.passed)
        self.assertFalse(legacy_audit.passed)
        self.assertFalse(inc_audit.passed)

    def test_audit_pass_matches(self) -> None:
        """audit_pass field identical for stale-evidence scenario."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow)
            _seed_stale_leak_state(uow)
            uow.commit()

            legacy_capsule = _legacy_compile(uow)
            inc_result = IncrementalDecisionCompiler(uow, TOKEN_BUDGET).compile(SESSION_ID)

        legacy_audit = self.audit.audit(legacy_capsule)
        inc_audit = self.audit.audit(inc_result.capsule)

        self.assertEqual(legacy_audit.passed, inc_audit.passed)

    def test_hard_fail_reasons_match(self) -> None:
        """hard_fail_reasons identical between paths."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow)
            _seed_block_state(uow)
            uow.commit()

            legacy_capsule = _legacy_compile(uow)
            inc_result = IncrementalDecisionCompiler(uow, TOKEN_BUDGET).compile(SESSION_ID)

        legacy_audit = self.audit.audit(legacy_capsule)
        inc_audit = self.audit.audit(inc_result.capsule)

        self.assertEqual(
            sorted(legacy_audit.hard_fail_reasons),
            sorted(inc_audit.hard_fail_reasons),
        )

    def test_open_obligation_ids_match(self) -> None:
        """open_obligation_ids identical."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow)
            _seed_multi_state(uow)
            uow.commit()

            legacy_capsule = _legacy_compile(uow)
            inc_result = IncrementalDecisionCompiler(uow, TOKEN_BUDGET).compile(SESSION_ID)

        self.assertEqual(
            legacy_capsule.audit_inputs.get("open_obligation_ids"),
            inc_result.capsule.audit_inputs.get("open_obligation_ids"),
        )

    def test_rendered_obligation_ids_match(self) -> None:
        """rendered_obligation_ids identical."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow)
            _seed_multi_state(uow)
            uow.commit()

            legacy_capsule = _legacy_compile(uow)
            inc_result = IncrementalDecisionCompiler(uow, TOKEN_BUDGET).compile(SESSION_ID)

        self.assertEqual(
            sorted(legacy_capsule.audit_inputs.get("rendered_obligation_ids", [])),
            sorted(inc_result.capsule.audit_inputs.get("rendered_obligation_ids", [])),
        )

    def test_live_stale_ticket_ids_match(self) -> None:
        """live_stale_ticket_ids identical."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow)
            _seed_stale_leak_state(uow)
            uow.commit()

            legacy_capsule = _legacy_compile(uow)
            inc_result = IncrementalDecisionCompiler(uow, TOKEN_BUDGET).compile(SESSION_ID)

        self.assertEqual(
            sorted(legacy_capsule.audit_inputs.get("live_stale_ticket_ids", [])),
            sorted(inc_result.capsule.audit_inputs.get("live_stale_ticket_ids", [])),
        )

    def test_reopened_obligation_ids_match(self) -> None:
        """reopened_obligation_ids identical."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow)
            _seed_reopened_state(uow)
            uow.commit()

            legacy_capsule = _legacy_compile(uow)
            inc_result = IncrementalDecisionCompiler(uow, TOKEN_BUDGET).compile(SESSION_ID)

        self.assertEqual(
            sorted(legacy_capsule.audit_inputs.get("reopened_obligation_ids", [])),
            sorted(inc_result.capsule.audit_inputs.get("reopened_obligation_ids", [])),
        )

    def test_next_checks_match(self) -> None:
        """next_checks entries identical."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow)
            _seed_multi_state(uow)
            uow.commit()

            legacy_capsule = _legacy_compile(uow)
            inc_result = IncrementalDecisionCompiler(uow, TOKEN_BUDGET).compile(SESSION_ID)

        self.assertEqual(
            sorted(legacy_capsule.next_checks),
            sorted(inc_result.capsule.next_checks),
        )

    def test_failed_family_negative_evidence_match(self) -> None:
        """Failed attempt families appear as negative evidence in both paths."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow)
            _seed_failed_family_state(uow)
            uow.commit()

            legacy_capsule = _legacy_compile(uow)
            inc_result = IncrementalDecisionCompiler(uow, TOKEN_BUDGET).compile(SESSION_ID)

        legacy_block = legacy_capsule.obligation_blocks[0]
        inc_block = inc_result.capsule.obligation_blocks[0]

        self.assertEqual(legacy_block.negative_items, inc_block.negative_items)
        self.assertEqual(legacy_block.suggested_next_check, inc_block.suggested_next_check)

    def test_incremental_flag_routes_correctly(self) -> None:
        """UserPromptSubmitService uses incremental path when flag is on."""
        config_inc = RuntimeConfig(
            repo_root=self.paths.repo_root,
            egtsr_dir=self.paths.egtsr_dir,
            db_path=self.paths.db_path,
            enable_incremental_compile=True,
        )
        envelope = parse_hook_stdin(json.dumps({
            "session_id": SESSION_ID,
            "cwd": self.paths.repo_root,
            "hook_event_name": "UserPromptSubmit",
            "prompt": "read the file",
            "source": "startup",
        }))

        with SqliteUnitOfWork(config_inc) as uow:
            _seed_session(uow)
            _seed_allow_state(uow)
            uow.commit()
            result = UserPromptSubmitService(
                uow, config_inc, self.paths.raw_events_dir
            ).handle(envelope)

        self.assertTrue(result.allowed)
        self.assertTrue(result.audit_report.passed)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _legacy_compile(uow):
    compiler_input = DecisionCompilerInput(
        session_id=SESSION_ID,
        token_budget=TOKEN_BUDGET,
        open_obligations=uow.obligations.list_open(SESSION_ID),
        evidence=uow.evidence.list_for_session(SESSION_ID),
        assertions=uow.assertions.list_for_session(SESSION_ID),
        invalidation_tickets=uow.invalidations.list_for_session(SESSION_ID),
        attempt_families=uow.attempt_families.list_for_session(SESSION_ID),
    )
    return DecisionCapsuleCompiler().compile(compiler_input)


def _seed_session(uow):
    uow.sessions.create(Session(
        id=SESSION_ID, repo_root="/tmp/test", branch="main",
        head_hash="abc", status="active",
        created_at="2026-03-31T10:00:00Z", updated_at="2026-03-31T10:00:00Z",
    ))


def _seed_allow_state(uow):
    """Single obligation with supported assertion — audit passes."""
    conn = uow._require_connection()
    obl = Obligation(
        id="obl-allow", session_id=SESSION_ID, source="spec",
        statement="Allow test", priority=10, status=ObligationStatus.OPEN,
        created_at="2026-03-31T10:00:00Z", updated_at="2026-03-31T10:00:00Z",
    )
    uow.obligations.upsert(obl)
    on_obligation_upsert(conn, obl)

    ev = Evidence(
        id="ev-allow", session_id=SESSION_ID, kind="command",
        source_tool="pytest", path="tests/a.py", polarity="positive",
        excerpt="pass", created_at="2026-03-31T10:01:00Z",
    )
    uow.evidence.create(ev)
    on_evidence_create(conn, ev)

    asn = Assertion(
        id="as-allow", session_id=SESSION_ID, obligation_id="obl-allow",
        statement="Supported", status=AssertionStatus.SUPPORTED,
        confidence=0.9, evidence_ids=["ev-allow"],
        created_at="2026-03-31T10:02:00Z", updated_at="2026-03-31T10:02:00Z",
    )
    uow.assertions.upsert(asn)
    on_assertion_upsert(conn, asn)


def _seed_block_state(uow):
    """Obligation with only confirmed assertion (no supported) — audit fails."""
    conn = uow._require_connection()
    obl = Obligation(
        id="obl-block", session_id=SESSION_ID, source="spec",
        statement="Block test", priority=10, status=ObligationStatus.OPEN,
        created_at="2026-03-31T10:00:00Z", updated_at="2026-03-31T10:00:00Z",
    )
    uow.obligations.upsert(obl)
    on_obligation_upsert(conn, obl)

    ev = Evidence(
        id="ev-block", session_id=SESSION_ID, kind="command",
        source_tool="pytest", path="tests/b.py", polarity="positive",
        excerpt="confirmed only", created_at="2026-03-31T10:01:00Z",
    )
    uow.evidence.create(ev)
    on_evidence_create(conn, ev)

    asn = Assertion(
        id="as-block", session_id=SESSION_ID, obligation_id="obl-block",
        statement="Unsupported confirmed", status=AssertionStatus.CONFIRMED,
        confidence=0.95, evidence_ids=["ev-block"],
        created_at="2026-03-31T10:02:00Z", updated_at="2026-03-31T10:02:00Z",
    )
    uow.assertions.upsert(asn)
    on_assertion_upsert(conn, asn)


def _seed_stale_leak_state(uow):
    """Obligation + live stale ticket on evidence — stale evidence leak."""
    conn = uow._require_connection()
    obl = Obligation(
        id="obl-stale", session_id=SESSION_ID, source="spec",
        statement="Stale leak test", priority=10, status=ObligationStatus.OPEN,
        created_at="2026-03-31T10:00:00Z", updated_at="2026-03-31T10:00:00Z",
    )
    uow.obligations.upsert(obl)
    on_obligation_upsert(conn, obl)

    ev = Evidence(
        id="ev-stale", session_id=SESSION_ID, kind="command",
        source_tool="pytest", path="tests/s.py", polarity="positive",
        excerpt="stale evidence", created_at="2026-03-31T10:01:00Z",
    )
    uow.evidence.create(ev)
    on_evidence_create(conn, ev)

    asn = Assertion(
        id="as-stale", session_id=SESSION_ID, obligation_id="obl-stale",
        statement="Stale linked", status=AssertionStatus.SUPPORTED,
        confidence=0.9, evidence_ids=["ev-stale"],
        created_at="2026-03-31T10:02:00Z", updated_at="2026-03-31T10:02:00Z",
    )
    uow.assertions.upsert(asn)
    on_assertion_upsert(conn, asn)

    ticket = InvalidationTicket(
        id="ticket-stale", session_id=SESSION_ID,
        subject_type="evidence", subject_id="ev-stale",
        trigger_kind="file_changed", trigger_ref="tests/s.py",
        status=InvalidationStatus.LIVE,
        created_at="2026-03-31T10:03:00Z", updated_at="2026-03-31T10:03:00Z",
    )
    uow.invalidations.upsert(ticket)
    on_invalidation_upsert(conn, ticket)


def _seed_multi_state(uow):
    """Two obligations with different priorities and states."""
    conn = uow._require_connection()
    for obl_id, label, priority, status in [
        ("obl-hi", "High", 10, ObligationStatus.OPEN),
        ("obl-lo", "Low", 3, ObligationStatus.LOCALIZED),
    ]:
        obl = Obligation(
            id=obl_id, session_id=SESSION_ID, source="spec",
            statement=f"Obligation {label}", priority=priority, status=status,
            created_at="2026-03-31T10:00:00Z", updated_at="2026-03-31T10:00:00Z",
        )
        uow.obligations.upsert(obl)
        on_obligation_upsert(conn, obl)

        ev = Evidence(
            id=f"ev-{obl_id}", session_id=SESSION_ID, kind="command",
            source_tool="pytest", path=f"tests/{label.lower()}.py",
            polarity="positive", excerpt=f"{label} pass",
            created_at="2026-03-31T10:01:00Z",
        )
        uow.evidence.create(ev)
        on_evidence_create(conn, ev)

        asn = Assertion(
            id=f"as-{obl_id}", session_id=SESSION_ID, obligation_id=obl_id,
            statement=f"{label} works", status=AssertionStatus.SUPPORTED,
            confidence=0.9, evidence_ids=[f"ev-{obl_id}"],
            created_at="2026-03-31T10:02:00Z", updated_at="2026-03-31T10:02:00Z",
        )
        uow.assertions.upsert(asn)
        on_assertion_upsert(conn, asn)


def _seed_reopened_state(uow):
    """One reopened + one open obligation."""
    conn = uow._require_connection()
    for obl_id, status in [
        ("obl-open", ObligationStatus.OPEN),
        ("obl-reopen", ObligationStatus.REOPENED),
    ]:
        obl = Obligation(
            id=obl_id, session_id=SESSION_ID, source="spec",
            statement=f"Obligation {obl_id}", priority=5, status=status,
            created_at="2026-03-31T10:00:00Z", updated_at="2026-03-31T10:00:00Z",
        )
        uow.obligations.upsert(obl)
        on_obligation_upsert(conn, obl)

        ev = Evidence(
            id=f"ev-{obl_id}", session_id=SESSION_ID, kind="command",
            source_tool="pytest", path=f"tests/{obl_id}.py",
            polarity="positive", excerpt="pass",
            created_at="2026-03-31T10:01:00Z",
        )
        uow.evidence.create(ev)
        on_evidence_create(conn, ev)

        asn = Assertion(
            id=f"as-{obl_id}", session_id=SESSION_ID, obligation_id=obl_id,
            statement=f"Assert {obl_id}", status=AssertionStatus.SUPPORTED,
            confidence=0.9, evidence_ids=[f"ev-{obl_id}"],
            created_at="2026-03-31T10:02:00Z", updated_at="2026-03-31T10:02:00Z",
        )
        uow.assertions.upsert(asn)
        on_assertion_upsert(conn, asn)


def _seed_failed_family_state(uow):
    """Obligation with recent failed attempt family."""
    conn = uow._require_connection()
    obl = Obligation(
        id="obl-fail", session_id=SESSION_ID, source="spec",
        statement="Failed family test", priority=10,
        status=ObligationStatus.OPEN,
        created_at="2026-03-31T10:00:00Z", updated_at="2026-03-31T10:00:00Z",
    )
    uow.obligations.upsert(obl)
    on_obligation_upsert(conn, obl)

    ev = Evidence(
        id="ev-fail", session_id=SESSION_ID, kind="command",
        source_tool="pytest", path="tests/fail.py", polarity="positive",
        excerpt="fail pass", created_at="2026-03-31T10:01:00Z",
    )
    uow.evidence.create(ev)
    on_evidence_create(conn, ev)

    asn = Assertion(
        id="as-fail", session_id=SESSION_ID, obligation_id="obl-fail",
        statement="Fail assertion", status=AssertionStatus.SUPPORTED,
        confidence=0.9, evidence_ids=["ev-fail"],
        created_at="2026-03-31T10:02:00Z", updated_at="2026-03-31T10:02:00Z",
    )
    uow.assertions.upsert(asn)
    on_assertion_upsert(conn, asn)

    family = AttemptFamily(
        id="fam-fail", session_id=SESSION_ID, obligation_id="obl-fail",
        signature="test::fail_sig", touched_scope=["tests/fail.py"],
        fail_count=3, last_outcome="fail",
        summary="Three failed attempts at fix",
        created_at="2026-03-31T10:03:00Z", updated_at="2026-03-31T10:03:00Z",
    )
    uow.attempt_families.upsert(family)
    on_attempt_family_upsert(conn, family)


if __name__ == "__main__":
    unittest.main()

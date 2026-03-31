"""Test that incremental compiler produces the same critical fields as legacy."""
from __future__ import annotations

import tempfile
import unittest

from egtsr_runtime.compiler import DecisionCapsuleCompiler, DecisionCompilerInput
from egtsr_runtime.compiler.incremental import IncrementalDecisionCompiler
from egtsr_runtime.config import RuntimeConfig
from egtsr_runtime.db.uow import SqliteUnitOfWork
from egtsr_runtime.enums import AssertionStatus, InvalidationStatus, ObligationStatus
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

SESSION_ID = "sess-equiv"
TOKEN_BUDGET = 900


class TestIncrementalEquivalence(unittest.TestCase):
    """Incremental compile must match legacy compile on critical fields."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.paths = ensure_runtime_dirs(self.tmp.name)
        self.config = RuntimeConfig(
            repo_root=self.paths.repo_root,
            egtsr_dir=self.paths.egtsr_dir,
            db_path=self.paths.db_path,
        )

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_single_obligation_all_dirty(self) -> None:
        """Single dirty obligation: incremental == legacy."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow)
            _seed_basic_state(uow)
            uow.commit()

            legacy_capsule = _legacy_compile(uow)
            inc_result = IncrementalDecisionCompiler(uow, TOKEN_BUDGET).compile(SESSION_ID)

        self._assert_critical_match(legacy_capsule, inc_result.capsule)
        self.assertTrue(inc_result.used_incremental)

    def test_multiple_obligations_all_dirty(self) -> None:
        """Multiple dirty obligations: incremental == legacy."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow)
            _seed_multi_obligation_state(uow)
            uow.commit()

            legacy_capsule = _legacy_compile(uow)
            inc_result = IncrementalDecisionCompiler(uow, TOKEN_BUDGET).compile(SESSION_ID)

        self._assert_critical_match(legacy_capsule, inc_result.capsule)

    def test_reopened_obligation_ordering(self) -> None:
        """Reopened obligation appears first in both paths."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow)
            _seed_reopened_state(uow)
            uow.commit()

            legacy_capsule = _legacy_compile(uow)
            inc_result = IncrementalDecisionCompiler(uow, TOKEN_BUDGET).compile(SESSION_ID)

        self._assert_critical_match(legacy_capsule, inc_result.capsule)
        self.assertEqual(inc_result.capsule.header_obligations[0], "obl-reopened")

    def test_stale_evidence_leak_matches(self) -> None:
        """stale_evidence_ids_seen matches between incremental and legacy."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow)
            _seed_stale_evidence_state(uow)
            uow.commit()

            legacy_capsule = _legacy_compile(uow)
            inc_result = IncrementalDecisionCompiler(uow, TOKEN_BUDGET).compile(SESSION_ID)

        self._assert_critical_match(legacy_capsule, inc_result.capsule)

    def test_unsupported_confirmed_matches(self) -> None:
        """unsupported_confirmed_assertion_ids matches between paths."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow)
            _seed_unsupported_confirmed_state(uow)
            uow.commit()

            legacy_capsule = _legacy_compile(uow)
            inc_result = IncrementalDecisionCompiler(uow, TOKEN_BUDGET).compile(SESSION_ID)

        self._assert_critical_match(legacy_capsule, inc_result.capsule)

    def _assert_critical_match(self, legacy, incremental) -> None:
        """Assert critical fields match per doc section 8."""
        legacy_ai = legacy.audit_inputs or {}
        inc_ai = incremental.audit_inputs or {}

        # open_obligation_ids
        self.assertEqual(
            legacy_ai.get("open_obligation_ids"),
            inc_ai.get("open_obligation_ids"),
        )
        # rendered_obligation_ids
        self.assertEqual(
            sorted(legacy_ai.get("rendered_obligation_ids", [])),
            sorted(inc_ai.get("rendered_obligation_ids", [])),
        )
        # stale_evidence_ids_seen
        self.assertEqual(
            sorted(legacy_ai.get("stale_evidence_ids_seen", [])),
            sorted(inc_ai.get("stale_evidence_ids_seen", [])),
        )
        # unsupported_confirmed_assertion_ids
        self.assertEqual(
            sorted(legacy_ai.get("unsupported_confirmed_assertion_ids", [])),
            sorted(inc_ai.get("unsupported_confirmed_assertion_ids", [])),
        )
        # live_stale_ticket_ids
        self.assertEqual(
            sorted(legacy_ai.get("live_stale_ticket_ids", [])),
            sorted(inc_ai.get("live_stale_ticket_ids", [])),
        )
        # reopened_obligation_ids
        self.assertEqual(
            sorted(legacy_ai.get("reopened_obligation_ids", [])),
            sorted(inc_ai.get("reopened_obligation_ids", [])),
        )
        # Block-level: same obligation blocks rendered
        legacy_block_ids = [b.obligation_id for b in legacy.obligation_blocks]
        inc_block_ids = [b.obligation_id for b in incremental.obligation_blocks]
        self.assertEqual(legacy_block_ids, inc_block_ids)


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


def _seed_basic_state(uow):
    """Single obligation with supported assertion + evidence."""
    conn = uow._require_connection()
    obl = Obligation(
        id="obl-1", session_id=SESSION_ID, source="spec",
        statement="Implement feature X", priority=10,
        status=ObligationStatus.OPEN,
        created_at="2026-03-31T10:00:00Z", updated_at="2026-03-31T10:00:00Z",
    )
    uow.obligations.upsert(obl)
    on_obligation_upsert(conn, obl)

    ev = Evidence(
        id="ev-1", session_id=SESSION_ID, kind="command",
        source_tool="pytest", path="tests/test_x.py",
        polarity="positive", excerpt="test passed",
        created_at="2026-03-31T10:01:00Z",
    )
    uow.evidence.create(ev)
    on_evidence_create(conn, ev)

    asn = Assertion(
        id="as-1", session_id=SESSION_ID, obligation_id="obl-1",
        statement="Feature X works", status=AssertionStatus.SUPPORTED,
        confidence=0.9, evidence_ids=["ev-1"],
        created_at="2026-03-31T10:02:00Z", updated_at="2026-03-31T10:02:00Z",
    )
    uow.assertions.upsert(asn)
    on_assertion_upsert(conn, asn)


def _seed_multi_obligation_state(uow):
    """Two obligations with different assertion states."""
    conn = uow._require_connection()

    obl1 = Obligation(
        id="obl-a", session_id=SESSION_ID, source="spec",
        statement="Obligation A", priority=10, status=ObligationStatus.OPEN,
        created_at="2026-03-31T10:00:00Z", updated_at="2026-03-31T10:00:00Z",
    )
    obl2 = Obligation(
        id="obl-b", session_id=SESSION_ID, source="spec",
        statement="Obligation B", priority=5, status=ObligationStatus.LOCALIZED,
        created_at="2026-03-31T10:00:01Z", updated_at="2026-03-31T10:00:01Z",
    )
    for obl in (obl1, obl2):
        uow.obligations.upsert(obl)
        on_obligation_upsert(conn, obl)

    ev = Evidence(
        id="ev-a", session_id=SESSION_ID, kind="command",
        source_tool="pytest", path="tests/a.py", polarity="positive",
        excerpt="a passed", created_at="2026-03-31T10:01:00Z",
    )
    uow.evidence.create(ev)
    on_evidence_create(conn, ev)

    as1 = Assertion(
        id="as-a", session_id=SESSION_ID, obligation_id="obl-a",
        statement="A works", status=AssertionStatus.SUPPORTED,
        confidence=0.9, evidence_ids=["ev-a"],
        created_at="2026-03-31T10:02:00Z", updated_at="2026-03-31T10:02:00Z",
    )
    as2 = Assertion(
        id="as-b", session_id=SESSION_ID, obligation_id="obl-b",
        statement="B speculative", status=AssertionStatus.SPECULATIVE,
        confidence=0.5, evidence_ids=[],
        created_at="2026-03-31T10:02:01Z", updated_at="2026-03-31T10:02:01Z",
    )
    for asn in (as1, as2):
        uow.assertions.upsert(asn)
        on_assertion_upsert(conn, asn)


def _seed_reopened_state(uow):
    """One reopened + one open obligation."""
    conn = uow._require_connection()

    obl_open = Obligation(
        id="obl-open", session_id=SESSION_ID, source="spec",
        statement="Open obligation", priority=5, status=ObligationStatus.OPEN,
        created_at="2026-03-31T10:00:00Z", updated_at="2026-03-31T10:00:00Z",
    )
    obl_reopen = Obligation(
        id="obl-reopened", session_id=SESSION_ID, source="spec",
        statement="Reopened obligation", priority=5, status=ObligationStatus.REOPENED,
        created_at="2026-03-31T10:00:01Z", updated_at="2026-03-31T10:00:01Z",
    )
    for obl in (obl_open, obl_reopen):
        uow.obligations.upsert(obl)
        on_obligation_upsert(conn, obl)

    ev = Evidence(
        id="ev-r", session_id=SESSION_ID, kind="command",
        source_tool="pytest", path="tests/r.py", polarity="positive",
        excerpt="r passed", created_at="2026-03-31T10:01:00Z",
    )
    uow.evidence.create(ev)
    on_evidence_create(conn, ev)

    for obl_id, asn_id in [("obl-open", "as-open"), ("obl-reopened", "as-reopen")]:
        asn = Assertion(
            id=asn_id, session_id=SESSION_ID, obligation_id=obl_id,
            statement=f"Assertion for {obl_id}", status=AssertionStatus.SUPPORTED,
            confidence=0.9, evidence_ids=["ev-r"],
            created_at="2026-03-31T10:02:00Z", updated_at="2026-03-31T10:02:00Z",
        )
        uow.assertions.upsert(asn)
        on_assertion_upsert(conn, asn)


def _seed_stale_evidence_state(uow):
    """Obligation + live stale ticket on evidence."""
    conn = uow._require_connection()

    obl = Obligation(
        id="obl-stale", session_id=SESSION_ID, source="spec",
        statement="Stale test", priority=10, status=ObligationStatus.OPEN,
        created_at="2026-03-31T10:00:00Z", updated_at="2026-03-31T10:00:00Z",
    )
    uow.obligations.upsert(obl)
    on_obligation_upsert(conn, obl)

    ev = Evidence(
        id="ev-stale", session_id=SESSION_ID, kind="command",
        source_tool="pytest", path="tests/stale.py", polarity="positive",
        excerpt="stale evidence", created_at="2026-03-31T10:01:00Z",
    )
    uow.evidence.create(ev)
    on_evidence_create(conn, ev)

    asn = Assertion(
        id="as-stale", session_id=SESSION_ID, obligation_id="obl-stale",
        statement="Stale assertion", status=AssertionStatus.SUPPORTED,
        confidence=0.9, evidence_ids=["ev-stale"],
        created_at="2026-03-31T10:02:00Z", updated_at="2026-03-31T10:02:00Z",
    )
    uow.assertions.upsert(asn)
    on_assertion_upsert(conn, asn)

    ticket = InvalidationTicket(
        id="ticket-stale", session_id=SESSION_ID,
        subject_type="evidence", subject_id="ev-stale",
        trigger_kind="file_changed", trigger_ref="tests/stale.py",
        status=InvalidationStatus.LIVE,
        created_at="2026-03-31T10:03:00Z", updated_at="2026-03-31T10:03:00Z",
    )
    uow.invalidations.upsert(ticket)
    on_invalidation_upsert(conn, ticket)


def _seed_unsupported_confirmed_state(uow):
    """Obligation with only a confirmed assertion (no supported)."""
    conn = uow._require_connection()

    obl = Obligation(
        id="obl-unsup", session_id=SESSION_ID, source="spec",
        statement="Unsupported confirmed test", priority=10,
        status=ObligationStatus.OPEN,
        created_at="2026-03-31T10:00:00Z", updated_at="2026-03-31T10:00:00Z",
    )
    uow.obligations.upsert(obl)
    on_obligation_upsert(conn, obl)

    ev = Evidence(
        id="ev-unsup", session_id=SESSION_ID, kind="command",
        source_tool="pytest", path="tests/unsup.py", polarity="positive",
        excerpt="unsup evidence", created_at="2026-03-31T10:01:00Z",
    )
    uow.evidence.create(ev)
    on_evidence_create(conn, ev)

    asn = Assertion(
        id="as-unsup", session_id=SESSION_ID, obligation_id="obl-unsup",
        statement="Confirmed but unsupported",
        status=AssertionStatus.CONFIRMED,
        confidence=0.95, evidence_ids=["ev-unsup"],
        created_at="2026-03-31T10:02:00Z", updated_at="2026-03-31T10:02:00Z",
    )
    uow.assertions.upsert(asn)
    on_assertion_upsert(conn, asn)


if __name__ == "__main__":
    unittest.main()

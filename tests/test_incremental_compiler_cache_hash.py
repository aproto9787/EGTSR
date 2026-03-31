"""Test render cache hash computation and cache invalidation."""
from __future__ import annotations

import tempfile
import unittest

from egtsr_runtime.compiler.cache_models import compute_render_hash
from egtsr_runtime.compiler.incremental import IncrementalDecisionCompiler
from egtsr_runtime.config import RuntimeConfig
from egtsr_runtime.db.uow import SqliteUnitOfWork
from egtsr_runtime.enums import AssertionStatus, ObligationStatus
from egtsr_runtime.models import Assertion, Evidence, Obligation, Session
from egtsr_runtime.paths import ensure_runtime_dirs
from egtsr_runtime.services.projections import (
    on_assertion_upsert,
    on_evidence_create,
    on_obligation_upsert,
)

SESSION_ID = "sess-hash"
TOKEN_BUDGET = 900


class TestRenderHash(unittest.TestCase):
    """Test compute_render_hash determinism and sensitivity."""

    def test_same_input_same_hash(self) -> None:
        h1 = compute_render_hash(
            obligation_id="obl-1",
            obligation_status="open",
            obligation_priority=10,
            assertion_summaries=[("as-1", "supported", "2026-03-31T10:00:00Z")],
            evidence_summaries=[("ev-1", "positive", "tests/x.py")],
            live_ticket_ids=[],
            failed_family_summaries=[],
            token_budget=900,
        )
        h2 = compute_render_hash(
            obligation_id="obl-1",
            obligation_status="open",
            obligation_priority=10,
            assertion_summaries=[("as-1", "supported", "2026-03-31T10:00:00Z")],
            evidence_summaries=[("ev-1", "positive", "tests/x.py")],
            live_ticket_ids=[],
            failed_family_summaries=[],
            token_budget=900,
        )
        self.assertEqual(h1, h2)

    def test_different_assertion_status_different_hash(self) -> None:
        h1 = compute_render_hash(
            obligation_id="obl-1", obligation_status="open", obligation_priority=10,
            assertion_summaries=[("as-1", "supported", "t")],
            evidence_summaries=[], live_ticket_ids=[], failed_family_summaries=[],
            token_budget=900,
        )
        h2 = compute_render_hash(
            obligation_id="obl-1", obligation_status="open", obligation_priority=10,
            assertion_summaries=[("as-1", "confirmed", "t")],
            evidence_summaries=[], live_ticket_ids=[], failed_family_summaries=[],
            token_budget=900,
        )
        self.assertNotEqual(h1, h2)

    def test_different_obligation_status_different_hash(self) -> None:
        h1 = compute_render_hash(
            obligation_id="obl-1", obligation_status="open", obligation_priority=10,
            assertion_summaries=[], evidence_summaries=[], live_ticket_ids=[],
            failed_family_summaries=[], token_budget=900,
        )
        h2 = compute_render_hash(
            obligation_id="obl-1", obligation_status="reopened", obligation_priority=10,
            assertion_summaries=[], evidence_summaries=[], live_ticket_ids=[],
            failed_family_summaries=[], token_budget=900,
        )
        self.assertNotEqual(h1, h2)

    def test_ticket_presence_changes_hash(self) -> None:
        h1 = compute_render_hash(
            obligation_id="obl-1", obligation_status="open", obligation_priority=10,
            assertion_summaries=[], evidence_summaries=[], live_ticket_ids=[],
            failed_family_summaries=[], token_budget=900,
        )
        h2 = compute_render_hash(
            obligation_id="obl-1", obligation_status="open", obligation_priority=10,
            assertion_summaries=[], evidence_summaries=[], live_ticket_ids=["ticket-1"],
            failed_family_summaries=[], token_budget=900,
        )
        self.assertNotEqual(h1, h2)

    def test_order_independent(self) -> None:
        """Hash should be the same regardless of input ordering."""
        h1 = compute_render_hash(
            obligation_id="obl-1", obligation_status="open", obligation_priority=10,
            assertion_summaries=[("as-2", "s", "t"), ("as-1", "c", "t")],
            evidence_summaries=[("ev-2", "p", "a"), ("ev-1", "n", "b")],
            live_ticket_ids=["t-2", "t-1"],
            failed_family_summaries=[("f-2", 3), ("f-1", 1)],
            token_budget=900,
        )
        h2 = compute_render_hash(
            obligation_id="obl-1", obligation_status="open", obligation_priority=10,
            assertion_summaries=[("as-1", "c", "t"), ("as-2", "s", "t")],
            evidence_summaries=[("ev-1", "n", "b"), ("ev-2", "p", "a")],
            live_ticket_ids=["t-1", "t-2"],
            failed_family_summaries=[("f-1", 1), ("f-2", 3)],
            token_budget=900,
        )
        self.assertEqual(h1, h2)


class TestCacheInvalidation(unittest.TestCase):
    """Test that cache is properly invalidated when data changes."""

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

    def test_cache_updated_after_rebuild(self) -> None:
        """After rebuilding a dirty block, frontier cache is updated."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow)
            _seed_basic_state(uow)
            uow.commit()

            inc = IncrementalDecisionCompiler(uow, TOKEN_BUDGET)
            result = inc.compile(SESSION_ID)
            uow.commit()

            # Check that frontier row has render cache populated
            fr = uow.obligation_frontier.get("obl-ch")
            self.assertIsNotNone(fr)
            self.assertFalse(fr.dirty)
            self.assertIsNotNone(fr.render_hash)
            self.assertIsNotNone(fr.last_rebuilt_at)
            self.assertTrue(fr.render_version > 0)
            self.assertIsNotNone(fr.suggested_next_check)

    def test_dirty_flag_cleared_after_compile(self) -> None:
        """After successful incremental compile, dirty flags are cleared."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow)
            _seed_basic_state(uow)
            uow.commit()

            inc = IncrementalDecisionCompiler(uow, TOKEN_BUDGET)
            inc.compile(SESSION_ID)
            uow.commit()

            dirty_ids = uow.obligation_frontier.list_dirty_ids(SESSION_ID)
            self.assertEqual(dirty_ids, [])


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_session(uow):
    uow.sessions.create(Session(
        id=SESSION_ID, repo_root="/tmp/test", branch="main",
        head_hash="abc", status="active",
        created_at="2026-03-31T10:00:00Z", updated_at="2026-03-31T10:00:00Z",
    ))


def _seed_basic_state(uow):
    conn = uow._require_connection()
    obl = Obligation(
        id="obl-ch", session_id=SESSION_ID, source="spec",
        statement="Cache hash test", priority=10,
        status=ObligationStatus.OPEN,
        created_at="2026-03-31T10:00:00Z", updated_at="2026-03-31T10:00:00Z",
    )
    uow.obligations.upsert(obl)
    on_obligation_upsert(conn, obl)

    ev = Evidence(
        id="ev-ch", session_id=SESSION_ID, kind="command",
        source_tool="pytest", path="tests/ch.py",
        polarity="positive", excerpt="ch pass",
        created_at="2026-03-31T10:01:00Z",
    )
    uow.evidence.create(ev)
    on_evidence_create(conn, ev)

    asn = Assertion(
        id="as-ch", session_id=SESSION_ID, obligation_id="obl-ch",
        statement="Cache hash assertion", status=AssertionStatus.SUPPORTED,
        confidence=0.9, evidence_ids=["ev-ch"],
        created_at="2026-03-31T10:02:00Z", updated_at="2026-03-31T10:02:00Z",
    )
    uow.assertions.upsert(asn)
    on_assertion_upsert(conn, asn)


if __name__ == "__main__":
    unittest.main()

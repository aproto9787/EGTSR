"""Test that incremental compiler rebuilds only dirty blocks."""
from __future__ import annotations

import json
import tempfile
import unittest

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

SESSION_ID = "sess-dirty"
TOKEN_BUDGET = 900


class TestDirtySubset(unittest.TestCase):
    """Verify that only dirty obligations trigger block rebuilds."""

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

    def test_dirty_zero_no_rebuild(self) -> None:
        """When all obligations are clean, rebuilt_count == 0."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow)
            _seed_two_obligations(uow)
            uow.commit()

            # First compile: all dirty
            inc = IncrementalDecisionCompiler(uow, TOKEN_BUDGET)
            first = inc.compile(SESSION_ID)
            uow.commit()
            self.assertTrue(first.used_incremental)
            self.assertEqual(first.dirty_count, 2)
            self.assertEqual(first.rebuilt_count, 2)

            # Second compile: nothing changed, all clean
            second = inc.compile(SESSION_ID)
            self.assertTrue(second.used_incremental)
            self.assertEqual(second.dirty_count, 0)
            self.assertEqual(second.rebuilt_count, 0)
            self.assertEqual(second.cache_hit_count, 2)

    def test_one_dirty_one_clean(self) -> None:
        """When one obligation is dirty, only that one is rebuilt."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow)
            _seed_two_obligations(uow)
            uow.commit()

            inc = IncrementalDecisionCompiler(uow, TOKEN_BUDGET)

            # First compile: all dirty
            first = inc.compile(SESSION_ID)
            uow.commit()
            self.assertEqual(first.rebuilt_count, 2)

            # Modify one obligation's assertion to make it dirty again
            conn = uow._require_connection()
            new_asn = Assertion(
                id="as-new-a", session_id=SESSION_ID, obligation_id="obl-a",
                statement="Updated assertion A", status=AssertionStatus.SUPPORTED,
                confidence=0.95, evidence_ids=["ev-a"],
                created_at="2026-03-31T10:05:00Z", updated_at="2026-03-31T10:05:00Z",
            )
            uow.assertions.upsert(new_asn)
            on_assertion_upsert(conn, new_asn)
            uow.commit()

            # Second compile: only obl-a should be dirty
            second = inc.compile(SESSION_ID)
            self.assertTrue(second.used_incremental)
            self.assertEqual(second.dirty_count, 1)
            self.assertEqual(second.rebuilt_count, 1)
            self.assertEqual(second.cache_hit_count, 1)

            # Both blocks still present
            block_ids = [b.obligation_id for b in second.capsule.obligation_blocks]
            self.assertIn("obl-a", block_ids)
            self.assertIn("obl-b", block_ids)

    def test_cache_preserves_block_content(self) -> None:
        """Cached block retains rendered items from previous compile."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow)
            _seed_two_obligations(uow)
            uow.commit()

            inc = IncrementalDecisionCompiler(uow, TOKEN_BUDGET)
            first = inc.compile(SESSION_ID)
            uow.commit()

            # Get block-b content from first compile
            first_b = next(
                b for b in first.capsule.obligation_blocks if b.obligation_id == "obl-b"
            )

            # Dirty only obl-a
            conn = uow._require_connection()
            new_asn = Assertion(
                id="as-extra-a", session_id=SESSION_ID, obligation_id="obl-a",
                statement="Extra A assertion", status=AssertionStatus.SPECULATIVE,
                confidence=0.3, evidence_ids=[],
                created_at="2026-03-31T10:06:00Z", updated_at="2026-03-31T10:06:00Z",
            )
            uow.assertions.upsert(new_asn)
            on_assertion_upsert(conn, new_asn)
            uow.commit()

            second = inc.compile(SESSION_ID)

            # Block-b should be identical (from cache)
            second_b = next(
                b for b in second.capsule.obligation_blocks if b.obligation_id == "obl-b"
            )
            self.assertEqual(first_b.positive_items, second_b.positive_items)
            self.assertEqual(first_b.negative_items, second_b.negative_items)
            self.assertEqual(first_b.uncertainty_items, second_b.uncertainty_items)
            self.assertEqual(first_b.suggested_next_check, second_b.suggested_next_check)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_session(uow):
    uow.sessions.create(Session(
        id=SESSION_ID, repo_root="/tmp/test", branch="main",
        head_hash="abc", status="active",
        created_at="2026-03-31T10:00:00Z", updated_at="2026-03-31T10:00:00Z",
    ))


def _seed_two_obligations(uow):
    conn = uow._require_connection()

    for obl_id, label, priority in [("obl-a", "A", 10), ("obl-b", "B", 5)]:
        obl = Obligation(
            id=obl_id, session_id=SESSION_ID, source="spec",
            statement=f"Obligation {label}", priority=priority,
            status=ObligationStatus.OPEN,
            created_at="2026-03-31T10:00:00Z", updated_at="2026-03-31T10:00:00Z",
        )
        uow.obligations.upsert(obl)
        on_obligation_upsert(conn, obl)

        ev = Evidence(
            id=f"ev-{obl_id[-1]}", session_id=SESSION_ID, kind="command",
            source_tool="pytest", path=f"tests/{label.lower()}.py",
            polarity="positive", excerpt=f"{label} passed",
            created_at="2026-03-31T10:01:00Z",
        )
        uow.evidence.create(ev)
        on_evidence_create(conn, ev)

        asn = Assertion(
            id=f"as-{obl_id[-1]}", session_id=SESSION_ID, obligation_id=obl_id,
            statement=f"{label} works", status=AssertionStatus.SUPPORTED,
            confidence=0.9, evidence_ids=[ev.id],
            created_at="2026-03-31T10:02:00Z", updated_at="2026-03-31T10:02:00Z",
        )
        uow.assertions.upsert(asn)
        on_assertion_upsert(conn, asn)


if __name__ == "__main__":
    unittest.main()

"""Test incremental compiler fallback conditions."""
from __future__ import annotations

import tempfile
import unittest
from unittest import mock

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

SESSION_ID = "sess-fallback"
TOKEN_BUDGET = 900


class TestIncrementalFallback(unittest.TestCase):
    """Verify graceful fallback to full compile."""

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

    def test_missing_frontier_row_triggers_fallback(self) -> None:
        """If obligation_frontier is missing for an open obligation, fall back."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow)
            # Create obligation WITHOUT syncing projection
            obl = Obligation(
                id="obl-no-proj", session_id=SESSION_ID, source="spec",
                statement="No projection", priority=10,
                status=ObligationStatus.OPEN,
                created_at="2026-03-31T10:00:00Z", updated_at="2026-03-31T10:00:00Z",
            )
            uow.obligations.upsert(obl)
            # Do NOT call on_obligation_upsert — frontier row missing

            ev = Evidence(
                id="ev-no-proj", session_id=SESSION_ID, kind="command",
                source_tool="pytest", path="tests/x.py", polarity="positive",
                excerpt="pass", created_at="2026-03-31T10:01:00Z",
            )
            uow.evidence.create(ev)

            asn = Assertion(
                id="as-no-proj", session_id=SESSION_ID, obligation_id="obl-no-proj",
                statement="No proj assertion", status=AssertionStatus.SUPPORTED,
                confidence=0.9, evidence_ids=["ev-no-proj"],
                created_at="2026-03-31T10:02:00Z", updated_at="2026-03-31T10:02:00Z",
            )
            uow.assertions.upsert(asn)
            uow.commit()

            result = IncrementalDecisionCompiler(uow, TOKEN_BUDGET).compile(SESSION_ID)

        self.assertFalse(result.used_incremental)
        self.assertIsNotNone(result.fallback_reason)
        self.assertIn("missing_frontier_rows", result.fallback_reason)
        # Capsule still produced via fallback
        self.assertTrue(result.capsule.rendered_text)

    def test_exception_triggers_fallback(self) -> None:
        """Exception during incremental path falls back to full compile."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow)
            _seed_basic_state(uow)
            uow.commit()

            inc = IncrementalDecisionCompiler(uow, TOKEN_BUDGET)

            # Simulate an exception in the incremental path
            with mock.patch.object(
                inc, "_try_incremental", side_effect=RuntimeError("projection corrupt")
            ):
                result = inc.compile(SESSION_ID)

        self.assertFalse(result.used_incremental)
        self.assertIn("exception", result.fallback_reason)
        self.assertTrue(result.capsule.rendered_text)

    def test_no_open_obligations_returns_empty(self) -> None:
        """Session with no open obligations returns empty capsule."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow)
            uow.commit()

            result = IncrementalDecisionCompiler(uow, TOKEN_BUDGET).compile(SESSION_ID)

        self.assertTrue(result.used_incremental)
        self.assertEqual(result.capsule.header_obligations, [])
        self.assertEqual(result.capsule.obligation_blocks, [])

    def test_stale_cache_promoted_to_dirty(self) -> None:
        """Clean obligation with no render_hash is promoted to dirty."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow)
            _seed_basic_state(uow)
            uow.commit()

            inc = IncrementalDecisionCompiler(uow, TOKEN_BUDGET)

            # First compile: builds cache
            first = inc.compile(SESSION_ID)
            uow.commit()
            self.assertTrue(first.used_incremental)

            # Manually clear render_hash to simulate stale cache
            conn = uow._require_connection()
            conn.execute(
                "UPDATE obligation_frontier SET render_hash = NULL WHERE obligation_id = ?",
                ("obl-fb",),
            )
            # But keep dirty = 0 (simulates dirty flag missed)
            conn.execute(
                "UPDATE obligation_frontier SET dirty = 0 WHERE obligation_id = ?",
                ("obl-fb",),
            )
            uow.commit()

            # Second compile: clean obligation with no render_hash → promoted to dirty
            second = inc.compile(SESSION_ID)
            self.assertTrue(second.used_incremental)
            self.assertEqual(second.rebuilt_count, 1)  # was promoted to dirty
            self.assertTrue(second.capsule.rendered_text)

    def test_projection_rebuild_forces_dirty(self) -> None:
        """After projection rebuild all obligations are dirty → rebuild all."""
        from egtsr_runtime.services.projection_backfill import rebuild_session_projections

        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow)
            _seed_basic_state(uow)
            uow.commit()

            inc = IncrementalDecisionCompiler(uow, TOKEN_BUDGET)

            # First compile
            first = inc.compile(SESSION_ID)
            uow.commit()
            self.assertTrue(first.used_incremental)

            # Simulate projection rebuild (clears and re-creates all frontier rows)
            conn = uow._require_connection()
            rebuild_session_projections(conn, SESSION_ID)
            uow.commit()

            # After rebuild: all obligations are dirty with render_hash = None
            fr = uow.obligation_frontier.get("obl-fb")
            self.assertTrue(fr.dirty)
            self.assertIsNone(fr.render_hash)

            # Second compile: everything is dirty
            second = inc.compile(SESSION_ID)
            self.assertTrue(second.used_incremental)
            self.assertEqual(second.rebuilt_count, 1)

    def test_dirty_ratio_fallback(self) -> None:
        """When dirty ratio exceeds threshold after prior compile, fall back."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow)
            conn = uow._require_connection()
            # Create 10 obligations
            for i in range(10):
                obl = Obligation(
                    id=f"obl-{i}", session_id=SESSION_ID, source="spec",
                    statement=f"Obligation {i}", priority=10,
                    status=ObligationStatus.OPEN,
                    created_at=f"2026-03-31T10:00:{i:02d}Z",
                    updated_at=f"2026-03-31T10:00:{i:02d}Z",
                )
                uow.obligations.upsert(obl)
                on_obligation_upsert(conn, obl)

                ev = Evidence(
                    id=f"ev-{i}", session_id=SESSION_ID, kind="command",
                    source_tool="pytest", path=f"tests/{i}.py",
                    polarity="positive", excerpt=f"pass {i}",
                    created_at=f"2026-03-31T10:01:{i:02d}Z",
                )
                uow.evidence.create(ev)
                on_evidence_create(conn, ev)

                asn = Assertion(
                    id=f"as-{i}", session_id=SESSION_ID, obligation_id=f"obl-{i}",
                    statement=f"Assert {i}", status=AssertionStatus.SUPPORTED,
                    confidence=0.9, evidence_ids=[f"ev-{i}"],
                    created_at=f"2026-03-31T10:02:{i:02d}Z",
                    updated_at=f"2026-03-31T10:02:{i:02d}Z",
                )
                uow.assertions.upsert(asn)
                on_assertion_upsert(conn, asn)
            uow.commit()

            inc = IncrementalDecisionCompiler(uow, TOKEN_BUDGET)

            # First compile succeeds (no prior compile, threshold skipped)
            first = inc.compile(SESSION_ID)
            uow.commit()
            self.assertTrue(first.used_incremental)

            # Simulate session_frontier having a prior capsule ID
            uow.session_frontier.update_last_compiled(
                SESSION_ID, "capsule-prior", "hash-prior", "2026-03-31T10:05:00Z"
            )

            # Re-dirty all obligations (simulate projection rebuild)
            for i in range(10):
                on_obligation_upsert(conn, Obligation(
                    id=f"obl-{i}", session_id=SESSION_ID, source="spec",
                    statement=f"Obligation {i}", priority=10,
                    status=ObligationStatus.OPEN,
                    created_at=f"2026-03-31T10:00:{i:02d}Z",
                    updated_at=f"2026-03-31T10:06:{i:02d}Z",
                ))
            uow.commit()

            # Second compile: all dirty with prior compile → threshold triggers
            result = inc.compile(SESSION_ID)

        self.assertFalse(result.used_incremental)
        self.assertEqual(result.fallback_reason, "dirty_ratio_exceeded")
        self.assertEqual(len(result.capsule.obligation_blocks), 10)


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
        id="obl-fb", session_id=SESSION_ID, source="spec",
        statement="Fallback test", priority=10,
        status=ObligationStatus.OPEN,
        created_at="2026-03-31T10:00:00Z", updated_at="2026-03-31T10:00:00Z",
    )
    uow.obligations.upsert(obl)
    on_obligation_upsert(conn, obl)

    ev = Evidence(
        id="ev-fb", session_id=SESSION_ID, kind="command",
        source_tool="pytest", path="tests/fb.py",
        polarity="positive", excerpt="fb pass",
        created_at="2026-03-31T10:01:00Z",
    )
    uow.evidence.create(ev)
    on_evidence_create(conn, ev)

    asn = Assertion(
        id="as-fb", session_id=SESSION_ID, obligation_id="obl-fb",
        statement="FB assertion", status=AssertionStatus.SUPPORTED,
        confidence=0.9, evidence_ids=["ev-fb"],
        created_at="2026-03-31T10:02:00Z", updated_at="2026-03-31T10:02:00Z",
    )
    uow.assertions.upsert(asn)
    on_assertion_upsert(conn, asn)


if __name__ == "__main__":
    unittest.main()

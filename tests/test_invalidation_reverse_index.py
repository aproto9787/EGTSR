"""Tests for reverse-index invalidation (Step 06).

Verifies that when ``enable_reverse_index=True``, the invalidation
service produces the same results as the legacy path but without
session-wide scans.
"""
from __future__ import annotations

import tempfile
import unittest

from egtsr_runtime.config import RuntimeConfig
from egtsr_runtime.db.uow import SqliteUnitOfWork
from egtsr_runtime.enums import AssertionStatus, InvalidationStatus, ObligationStatus
from egtsr_runtime.models import Assertion, Evidence, Obligation, Session
from egtsr_runtime.paths import ensure_runtime_dirs
from egtsr_runtime.services.invalidation import FileTouchInvalidationService
from egtsr_runtime.services.projections import (
    on_assertion_upsert,
    on_evidence_create,
    on_obligation_upsert,
)


class _BaseReverseIndexTest(unittest.TestCase):
    """Shared setup for reverse-index invalidation tests."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.paths = ensure_runtime_dirs(self.tmp_dir.name)
        self.config = RuntimeConfig(
            repo_root=self.paths.repo_root,
            egtsr_dir=self.paths.egtsr_dir,
            db_path=self.paths.db_path,
            enable_reverse_index=True,
        )
        self.session_id = "sess-reverse-index"

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
                created_at="2026-03-31T10:00:00Z",
                updated_at="2026-03-31T10:00:00Z",
            )
        )

    def _make_obligation(
        self, obligation_id: str, status: ObligationStatus = ObligationStatus.OPEN
    ) -> Obligation:
        return Obligation(
            id=obligation_id,
            session_id=self.session_id,
            source="test",
            statement=f"Obligation {obligation_id}",
            priority=1,
            status=status,
            acceptance_check="pytest -q",
            metadata={},
            created_at="2026-03-31T10:01:00Z",
            updated_at="2026-03-31T10:01:00Z",
        )

    def _make_assertion(
        self,
        assertion_id: str,
        obligation_id: str,
        *,
        scope_ref: str | None,
        status: AssertionStatus = AssertionStatus.SUPPORTED,
        evidence_ids: list[str] | None = None,
        statement: str | None = None,
    ) -> Assertion:
        return Assertion(
            id=assertion_id,
            session_id=self.session_id,
            obligation_id=obligation_id,
            statement=statement or f"Assertion {assertion_id}",
            scope_kind="file" if scope_ref else None,
            scope_ref=scope_ref,
            status=status,
            confidence=0.9,
            evidence_ids=evidence_ids or [],
            metadata={},
            created_at="2026-03-31T10:02:00Z",
            updated_at="2026-03-31T10:02:00Z",
        )

    def _make_evidence(
        self, evidence_id: str, *, path: str, excerpt: str = "evidence excerpt"
    ) -> Evidence:
        return Evidence(
            id=evidence_id,
            session_id=self.session_id,
            kind="read_span",
            source_tool="Read",
            path=path,
            scope_kind="file",
            scope_ref=path,
            polarity="positive",
            excerpt=excerpt,
            metadata={},
            created_at="2026-03-31T10:03:00Z",
        )

    def _insert_with_projections(
        self,
        uow: SqliteUnitOfWork,
        *,
        obligations: list[Obligation] | None = None,
        evidence_items: list[Evidence] | None = None,
        assertions: list[Assertion] | None = None,
    ) -> None:
        """Insert entities and sync their projections."""
        conn = uow.conn
        for obl in obligations or []:
            uow.obligations.upsert(obl)
            on_obligation_upsert(conn, obl)
        for ev in evidence_items or []:
            uow.evidence.create(ev)
            on_evidence_create(conn, ev)
        for a in assertions or []:
            uow.assertions.upsert(a)
            on_assertion_upsert(conn, a)

    def _svc(self, uow: SqliteUnitOfWork) -> FileTouchInvalidationService:
        return FileTouchInvalidationService(uow, enable_reverse_index=True)

    def _legacy_svc(self, uow: SqliteUnitOfWork) -> FileTouchInvalidationService:
        return FileTouchInvalidationService(uow, enable_reverse_index=False)


class TestReverseIndexBasicInvalidation(_BaseReverseIndexTest):
    """Core invalidation behaviour with reverse-index."""

    def test_scope_ref_match_stales_assertion(self):
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            obl = self._make_obligation("obl-1")
            asrt = self._make_assertion("as-1", obl.id, scope_ref="src/main.py")
            self._insert_with_projections(uow, obligations=[obl], assertions=[asrt])

            result = self._svc(uow).apply(self.session_id, ["src/main.py"])
            uow.commit()

        with SqliteUnitOfWork(self.config.db_path) as uow:
            stored = uow.assertions.get("as-1")

        self.assertEqual(result.stale_assertion_ids, ["as-1"])
        self.assertEqual(stored.status, AssertionStatus.STALE)

    def test_evidence_path_match_stales_assertion(self):
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            obl = self._make_obligation("obl-1")
            ev = self._make_evidence("ev-1", path="src/helper.py")
            asrt = self._make_assertion(
                "as-1", obl.id, scope_ref="src/other.py", evidence_ids=["ev-1"]
            )
            self._insert_with_projections(
                uow, obligations=[obl], evidence_items=[ev], assertions=[asrt]
            )

            result = self._svc(uow).apply(self.session_id, ["src/helper.py"])
            uow.commit()

        self.assertEqual(result.stale_assertion_ids, ["as-1"])

    def test_unrelated_file_no_op(self):
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            obl = self._make_obligation("obl-1")
            asrt = self._make_assertion("as-1", obl.id, scope_ref="src/main.py")
            self._insert_with_projections(uow, obligations=[obl], assertions=[asrt])

            result = self._svc(uow).apply(self.session_id, ["src/unrelated.py"])
            uow.commit()

        self.assertEqual(result.stale_assertion_ids, [])
        self.assertEqual(result.reopened_obligation_ids, [])
        self.assertEqual(result.invalidation_ticket_ids, [])

    def test_already_stale_not_restaled(self):
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            obl = self._make_obligation("obl-1")
            asrt = self._make_assertion(
                "as-1", obl.id, scope_ref="src/main.py", status=AssertionStatus.STALE
            )
            self._insert_with_projections(uow, obligations=[obl], assertions=[asrt])

            result = self._svc(uow).apply(self.session_id, ["src/main.py"])
            uow.commit()

        self.assertEqual(result.stale_assertion_ids, [])
        self.assertEqual(result.invalidation_ticket_ids, [])

    def test_empty_changed_files_no_op(self):
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            result = self._svc(uow).apply(self.session_id, [])
            uow.commit()

        self.assertEqual(result.stale_assertion_ids, [])
        self.assertEqual(result.invalidation_ticket_ids, [])

    def test_invalidation_ticket_created(self):
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            obl = self._make_obligation("obl-1")
            ev = self._make_evidence("ev-1", path="src/main.py")
            asrt = self._make_assertion(
                "as-1", obl.id, scope_ref="src/other.py", evidence_ids=["ev-1"]
            )
            self._insert_with_projections(
                uow, obligations=[obl], evidence_items=[ev], assertions=[asrt]
            )

            self._svc(uow).apply(self.session_id, ["src/main.py"])
            uow.commit()

        with SqliteUnitOfWork(self.config.db_path) as uow:
            tickets = uow.invalidations.list_for_session(self.session_id)

        self.assertEqual(len(tickets), 2)  # evidence + assertion tickets
        evidence_tickets = [t for t in tickets if t.subject_type == "evidence"]
        assertion_tickets = [t for t in tickets if t.subject_type == "assertion"]
        self.assertEqual(len(evidence_tickets), 1)
        self.assertEqual(evidence_tickets[0].subject_id, "ev-1")
        self.assertEqual(len(assertion_tickets), 1)
        self.assertEqual(assertion_tickets[0].subject_id, "as-1")
        self.assertEqual(assertion_tickets[0].trigger_kind, "file_touch")
        self.assertEqual(assertion_tickets[0].trigger_ref, "src/main.py")


class TestReverseIndexReopenSemantics(_BaseReverseIndexTest):
    """Reopen semantics must match legacy behavior."""

    def test_verified_obligation_reopened(self):
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            obl = self._make_obligation("obl-1", status=ObligationStatus.VERIFIED)
            asrt = self._make_assertion("as-1", obl.id, scope_ref="src/main.py")
            self._insert_with_projections(uow, obligations=[obl], assertions=[asrt])

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
            asrt = self._make_assertion("as-1", obl.id, scope_ref="src/main.py")
            self._insert_with_projections(uow, obligations=[obl], assertions=[asrt])

            result = self._svc(uow).apply(self.session_id, ["src/main.py"])
            uow.commit()

        with SqliteUnitOfWork(self.config.db_path) as uow:
            stored = uow.obligations.get("obl-1")

        self.assertEqual(result.reopened_obligation_ids, [])
        self.assertEqual(stored.status, ObligationStatus.OPEN)

    def test_quarantine_not_delete(self):
        """Stale assertions are quarantined, not deleted."""
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            obl = self._make_obligation("obl-1")
            asrt = self._make_assertion("as-1", obl.id, scope_ref="src/main.py")
            self._insert_with_projections(uow, obligations=[obl], assertions=[asrt])

            self._svc(uow).apply(self.session_id, ["src/main.py"])
            uow.commit()

        with SqliteUnitOfWork(self.config.db_path) as uow:
            stored = uow.assertions.get("as-1")

        self.assertIsNotNone(stored)
        self.assertEqual(stored.status, AssertionStatus.STALE)


class TestReverseIndexEquivalence(_BaseReverseIndexTest):
    """Verify reverse-index produces same results as legacy."""

    def test_single_file_equivalence(self):
        """Legacy and reverse-index produce the same stale/reopen sets."""
        obl = self._make_obligation("obl-1", status=ObligationStatus.VERIFIED)
        ev = self._make_evidence("ev-1", path="src/main.py")
        asrt = self._make_assertion(
            "as-1", obl.id, scope_ref="src/other.py", evidence_ids=["ev-1"]
        )
        changed = ["src/main.py"]

        # Legacy run
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            self._insert_with_projections(
                uow, obligations=[obl], evidence_items=[ev], assertions=[asrt]
            )
            legacy_result = self._legacy_svc(uow).apply(self.session_id, changed)
            uow.commit()

        # Fresh DB for reverse-index run
        tmp2 = tempfile.TemporaryDirectory()
        paths2 = ensure_runtime_dirs(tmp2.name)
        config2 = RuntimeConfig(
            repo_root=paths2.repo_root,
            egtsr_dir=paths2.egtsr_dir,
            db_path=paths2.db_path,
            enable_reverse_index=True,
        )
        session_id2 = self.session_id

        obl2 = self._make_obligation("obl-1", status=ObligationStatus.VERIFIED)
        ev2 = self._make_evidence("ev-1", path="src/main.py")
        asrt2 = self._make_assertion(
            "as-1", obl2.id, scope_ref="src/other.py", evidence_ids=["ev-1"]
        )

        with SqliteUnitOfWork(config2) as uow:
            self._seed_session(uow)
            self._insert_with_projections(
                uow, obligations=[obl2], evidence_items=[ev2], assertions=[asrt2]
            )
            ri_result = self._svc(uow).apply(session_id2, changed)
            uow.commit()

        tmp2.cleanup()

        # Same stale/reopen sets (order may differ, IDs are deterministic)
        self.assertEqual(
            sorted(legacy_result.stale_assertion_ids),
            sorted(ri_result.stale_assertion_ids),
        )
        self.assertEqual(
            sorted(legacy_result.reopened_obligation_ids),
            sorted(ri_result.reopened_obligation_ids),
        )

    def test_multi_assertion_fanout(self):
        """Multiple assertions linked to same file all get staled."""
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            obl = self._make_obligation("obl-1")
            asrt1 = self._make_assertion("as-1", obl.id, scope_ref="src/shared.py")
            asrt2 = self._make_assertion("as-2", obl.id, scope_ref="src/shared.py")
            asrt3 = self._make_assertion("as-3", obl.id, scope_ref="src/other.py")
            self._insert_with_projections(
                uow, obligations=[obl], assertions=[asrt1, asrt2, asrt3]
            )

            result = self._svc(uow).apply(self.session_id, ["src/shared.py"])
            uow.commit()

        self.assertEqual(sorted(result.stale_assertion_ids), ["as-1", "as-2"])
        self.assertNotIn("as-3", result.stale_assertion_ids)


class TestReverseIndexFrontierDirty(_BaseReverseIndexTest):
    """Verify frontier dirty marking on invalidation."""

    def test_obligation_frontier_marked_dirty(self):
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            obl = self._make_obligation("obl-1")
            asrt = self._make_assertion("as-1", obl.id, scope_ref="src/main.py")
            self._insert_with_projections(uow, obligations=[obl], assertions=[asrt])

            self._svc(uow).apply(self.session_id, ["src/main.py"])
            uow.commit()

        with SqliteUnitOfWork(self.config.db_path) as uow:
            frontier = uow.obligation_frontier.get("obl-1")

        self.assertIsNotNone(frontier)
        self.assertTrue(frontier.dirty)
        self.assertIn("file_touch", frontier.dirty_reasons)


class TestDuplicatePathNormalization(_BaseReverseIndexTest):
    """Duplicate and unnormalized paths must be handled."""

    def test_duplicate_paths_deduped(self):
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            obl = self._make_obligation("obl-1")
            asrt = self._make_assertion("as-1", obl.id, scope_ref="src/main.py")
            self._insert_with_projections(uow, obligations=[obl], assertions=[asrt])

            result = self._svc(uow).apply(
                self.session_id, ["src/main.py", "src/main.py", "src/../src/main.py"]
            )
            uow.commit()

        # Only one stale — deduped
        self.assertEqual(result.stale_assertion_ids, ["as-1"])
        self.assertEqual(len(result.invalidation_ticket_ids), 1)


if __name__ == "__main__":
    unittest.main()

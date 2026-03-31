from __future__ import annotations

import tempfile
import unittest

from egtsr_runtime.compiler import DecisionCapsuleCompiler, DecisionCompilerInput
from egtsr_runtime.config import RuntimeConfig
from egtsr_runtime.db.uow import SqliteUnitOfWork
from egtsr_runtime.enums import AssertionStatus, ObligationStatus
from egtsr_runtime.models import Assertion, Evidence, Obligation, Session
from egtsr_runtime.paths import ensure_runtime_dirs
from egtsr_runtime.services import FileTouchInvalidationService


class TestFileTouchInvalidation(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.paths = ensure_runtime_dirs(self.tmp_dir.name)
        self.config = RuntimeConfig(
            repo_root=self.paths.repo_root,
            egtsr_dir=self.paths.egtsr_dir,
            db_path=self.paths.db_path,
        )
        self.session_id = "sess-invalidation"
        self.compiler = DecisionCapsuleCompiler()

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_changed_file_stales_related_assertion(self):
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            obligation = self._make_obligation("obl-1")
            assertion = self._make_assertion("as-1", obligation.id, scope_ref="/repo/src/main.py")
            uow.obligations.upsert(obligation)
            uow.assertions.upsert(assertion)

            result = FileTouchInvalidationService(uow).apply(self.session_id, ["/repo/src/main.py"])
            uow.commit()

        with SqliteUnitOfWork(self.config.db_path) as uow:
            stored = uow.assertions.get("as-1")

        self.assertEqual(result.stale_assertion_ids, ["as-1"])
        self.assertIsNotNone(stored)
        self.assertEqual(stored.status, AssertionStatus.STALE)

    def test_stale_excluded_from_capsule_body(self):
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            obligation = self._make_obligation("obl-1")
            evidence = self._make_evidence("ev-1", path="/repo/src/main.py", excerpt="stale evidence excerpt")
            assertion = self._make_assertion(
                "as-1",
                obligation.id,
                scope_ref="/repo/src/main.py",
                status=AssertionStatus.STALE,
                evidence_ids=[evidence.id],
                statement="Stale assertion",
            )
            uow.obligations.upsert(obligation)
            uow.evidence.create(evidence)
            uow.assertions.upsert(assertion)
            uow.commit()

        with SqliteUnitOfWork(self.config.db_path) as uow:
            capsule = self.compiler.compile(
                DecisionCompilerInput(
                    session_id=self.session_id,
                    token_budget=4000,
                    open_obligations=uow.obligations.list_open(self.session_id),
                    evidence=uow.evidence.list_for_session(self.session_id),
                    assertions=uow.assertions.list_for_session(self.session_id),
                    invalidation_tickets=uow.invalidations.list_for_session(self.session_id),
                    attempt_families=uow.attempt_families.list_for_session(self.session_id),
                )
            )

        block = capsule.obligation_blocks[0]
        body = "\n".join(block.positive_items + block.negative_items + block.uncertainty_items)
        self.assertNotIn("Stale assertion", body)
        self.assertNotIn("stale evidence excerpt", body)

    def test_verified_obligation_reopened(self):
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            obligation = self._make_obligation("obl-1", status=ObligationStatus.VERIFIED)
            assertion = self._make_assertion("as-1", obligation.id, scope_ref="/repo/src/main.py")
            uow.obligations.upsert(obligation)
            uow.assertions.upsert(assertion)

            result = FileTouchInvalidationService(uow).apply(self.session_id, ["/repo/src/main.py"])
            uow.commit()

        with SqliteUnitOfWork(self.config.db_path) as uow:
            stored = uow.obligations.get("obl-1")

        self.assertEqual(result.reopened_obligation_ids, ["obl-1"])
        self.assertIsNotNone(stored)
        self.assertEqual(stored.status, ObligationStatus.REOPENED)

    def test_invalidation_ticket_created(self):
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            obligation = self._make_obligation("obl-1")
            evidence = self._make_evidence("ev-1", path="/repo/src/main.py")
            assertion = self._make_assertion(
                "as-1",
                obligation.id,
                scope_ref="/repo/src/other.py",
                evidence_ids=[evidence.id],
            )
            uow.obligations.upsert(obligation)
            uow.evidence.create(evidence)
            uow.assertions.upsert(assertion)

            FileTouchInvalidationService(uow).apply(self.session_id, ["/repo/src/main.py"])
            uow.commit()

        with SqliteUnitOfWork(self.config.db_path) as uow:
            tickets = uow.invalidations.list_for_session(self.session_id)

        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0].subject_type, "assertion")
        self.assertEqual(tickets[0].subject_id, "as-1")
        self.assertEqual(tickets[0].trigger_kind, "file_touch")
        self.assertEqual(tickets[0].trigger_ref, "/repo/src/main.py")

    def test_unrelated_file_no_op(self):
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            obligation = self._make_obligation("obl-1")
            assertion = self._make_assertion("as-1", obligation.id, scope_ref="/repo/src/main.py")
            uow.obligations.upsert(obligation)
            uow.assertions.upsert(assertion)

            result = FileTouchInvalidationService(uow).apply(self.session_id, ["/repo/other.py"])
            uow.commit()

        with SqliteUnitOfWork(self.config.db_path) as uow:
            stored_assertion = uow.assertions.get("as-1")
            tickets = uow.invalidations.list_for_session(self.session_id)

        self.assertEqual(result.stale_assertion_ids, [])
        self.assertEqual(result.reopened_obligation_ids, [])
        self.assertEqual(result.invalidation_ticket_ids, [])
        self.assertIsNotNone(stored_assertion)
        self.assertEqual(stored_assertion.status, AssertionStatus.SUPPORTED)
        self.assertEqual(tickets, [])

    def test_already_stale_not_restaled(self):
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            obligation = self._make_obligation("obl-1")
            assertion = self._make_assertion(
                "as-1",
                obligation.id,
                scope_ref="/repo/src/main.py",
                status=AssertionStatus.STALE,
            )
            uow.obligations.upsert(obligation)
            uow.assertions.upsert(assertion)

            result = FileTouchInvalidationService(uow).apply(self.session_id, ["/repo/src/main.py"])
            uow.commit()

        with SqliteUnitOfWork(self.config.db_path) as uow:
            stored_assertion = uow.assertions.get("as-1")
            tickets = uow.invalidations.list_for_session(self.session_id)

        self.assertEqual(result.stale_assertion_ids, [])
        self.assertEqual(result.invalidation_ticket_ids, [])
        self.assertIsNotNone(stored_assertion)
        self.assertEqual(stored_assertion.status, AssertionStatus.STALE)
        self.assertEqual(tickets, [])

    def test_non_verified_obligation_not_reopened(self):
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            obligation = self._make_obligation("obl-1", status=ObligationStatus.OPEN)
            assertion = self._make_assertion("as-1", obligation.id, scope_ref="/repo/src/main.py")
            uow.obligations.upsert(obligation)
            uow.assertions.upsert(assertion)

            result = FileTouchInvalidationService(uow).apply(self.session_id, ["/repo/src/main.py"])
            uow.commit()

        with SqliteUnitOfWork(self.config.db_path) as uow:
            stored = uow.obligations.get("obl-1")

        self.assertEqual(result.reopened_obligation_ids, [])
        self.assertIsNotNone(stored)
        self.assertEqual(stored.status, ObligationStatus.OPEN)

    def test_quarantine_not_delete(self):
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            obligation = self._make_obligation("obl-1")
            assertion = self._make_assertion("as-1", obligation.id, scope_ref="/repo/src/main.py")
            uow.obligations.upsert(obligation)
            uow.assertions.upsert(assertion)

            FileTouchInvalidationService(uow).apply(self.session_id, ["/repo/src/main.py"])
            uow.commit()

        with SqliteUnitOfWork(self.config.db_path) as uow:
            stored = uow.assertions.get("as-1")
            assertions = uow.assertions.list_for_session(self.session_id)

        self.assertIsNotNone(stored)
        self.assertEqual(stored.status, AssertionStatus.STALE)
        self.assertEqual([item.id for item in assertions], ["as-1"])

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

    def _make_obligation(self, obligation_id: str, status: ObligationStatus = ObligationStatus.OPEN) -> Obligation:
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

    def _make_evidence(self, evidence_id: str, *, path: str, excerpt: str = "evidence excerpt") -> Evidence:
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


if __name__ == "__main__":
    unittest.main()

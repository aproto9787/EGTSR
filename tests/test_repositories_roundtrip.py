import json
import tempfile
import unittest
from pathlib import Path

from egtsr_runtime.config import RuntimeConfig
from egtsr_runtime.db.seed import seed_db
from egtsr_runtime.db.uow import SqliteUnitOfWork
from egtsr_runtime.enums import AssertionStatus, InvalidationStatus, ObligationStatus, VerifyPhase
from egtsr_runtime.models import (
    Assertion,
    AttemptFamily,
    Capsule,
    Event,
    Evidence,
    InvalidationTicket,
    Obligation,
    RepoState,
    Session,
    VerifyResult,
)
from egtsr_runtime.paths import ensure_runtime_dirs


class RepositoryRoundTripTests(unittest.TestCase):
    def _config(self) -> RuntimeConfig:
        self.tmp_dir = tempfile.TemporaryDirectory()
        paths = ensure_runtime_dirs(self.tmp_dir.name)
        return RuntimeConfig(
            repo_root=paths.repo_root,
            egtsr_dir=paths.egtsr_dir,
            db_path=paths.db_path,
        )

    def tearDown(self) -> None:
        if hasattr(self, "tmp_dir"):
            self.tmp_dir.cleanup()

    def test_round_trip_for_all_entities(self) -> None:
        config = self._config()
        session = Session(
            id="sess-1",
            repo_root=config.repo_root,
            branch="main",
            head_hash="abc123",
            status="active",
            created_at="2026-03-31T10:00:00Z",
            updated_at="2026-03-31T10:00:00Z",
        )
        repo_state = RepoState(
            session_id=session.id,
            head_hash="abc123",
            dirty=True,
            changed_files=["a.py", "b.py"],
            last_scan_at="2026-03-31T10:01:00Z",
        )
        obligation = Obligation(
            id="obl-1",
            session_id=session.id,
            source="doc",
            statement="Persist runtime state",
            priority=1,
            status=ObligationStatus.OPEN,
            acceptance_check="query returns row",
            metadata={"owner": "runtime"},
            created_at="2026-03-31T10:02:00Z",
            updated_at="2026-03-31T10:02:00Z",
        )
        evidence = Evidence(
            id="ev-1",
            session_id=session.id,
            kind="command",
            source_tool="pytest",
            path="tests/test_runtime.py",
            scope_kind="file",
            scope_ref="tests/test_runtime.py",
            file_hash="f1",
            polarity="positive",
            excerpt="green",
            metadata={"exit_code": 0},
            created_at="2026-03-31T10:03:00Z",
        )
        assertion = Assertion(
            id="as-1",
            session_id=session.id,
            obligation_id=obligation.id,
            statement="State is durable",
            scope_kind="repo",
            scope_ref=config.repo_root,
            status=AssertionStatus.CONFIRMED,
            confidence=0.99,
            evidence_ids=[evidence.id],
            metadata={"reviewed": True},
            created_at="2026-03-31T10:04:00Z",
            updated_at="2026-03-31T10:04:00Z",
        )
        invalidation = InvalidationTicket(
            id="inv-1",
            session_id=session.id,
            subject_type="assertion",
            subject_id=assertion.id,
            trigger_kind="file_change",
            trigger_ref="src/main.py",
            status=InvalidationStatus.LIVE,
            metadata={"reason": "code changed"},
            created_at="2026-03-31T10:05:00Z",
            updated_at="2026-03-31T10:05:00Z",
        )
        attempt_family = AttemptFamily(
            id="af-1",
            session_id=session.id,
            obligation_id=obligation.id,
            signature="fix:src/main.py",
            touched_scope=["src/main.py"],
            fail_count=2,
            last_outcome="failed",
            summary="Two failed attempts",
            metadata={"branch": "main"},
            created_at="2026-03-31T10:06:00Z",
            updated_at="2026-03-31T10:06:00Z",
        )
        verify_result = VerifyResult(
            id="vr-1",
            session_id=session.id,
            phase=VerifyPhase.BROAD_SMOKE,
            outcome="passed",
            affected_obligation_ids=[obligation.id],
            excerpt="smoke ok",
            metadata={"suite": "smoke"},
            created_at="2026-03-31T10:07:00Z",
        )
        capsule = Capsule(
            id="cap-1",
            session_id=session.id,
            phase=VerifyPhase.TARGETED,
            frontier_hash="frontier-1",
            content="capsule",
            token_count=32,
            audit_pass=True,
            audit_report={"ok": True},
            created_at="2026-03-31T10:08:00Z",
        )
        event = Event(
            id="evt-1",
            session_id=session.id,
            event_type="session.started",
            payload={"phase": 1},
            created_at="2026-03-31T10:09:00Z",
        )

        with SqliteUnitOfWork(config) as uow:
            uow.sessions.create(session)
            uow.repo_state.upsert(repo_state)
            uow.obligations.upsert(obligation)
            uow.evidence.create(evidence)
            uow.assertions.upsert(assertion)
            uow.invalidations.upsert(invalidation)
            uow.attempt_families.upsert(attempt_family)
            uow.verify_results.create(verify_result)
            uow.capsules.create(capsule)
            uow.events.create(event)
            uow.commit()

        with SqliteUnitOfWork(config.db_path) as uow:
            self.assertEqual(uow.sessions.get(session.id), session)
            self.assertEqual(uow.repo_state.get(session.id), repo_state)
            self.assertEqual(uow.obligations.get(obligation.id), obligation)
            self.assertEqual(uow.evidence.get(evidence.id), evidence)
            self.assertEqual(uow.assertions.get(assertion.id), assertion)
            self.assertEqual(uow.invalidations.get(invalidation.id), invalidation)
            self.assertEqual(uow.attempt_families.get(attempt_family.id), attempt_family)
            self.assertEqual(uow.verify_results.get(verify_result.id), verify_result)
            self.assertEqual(uow.capsules.get(capsule.id), capsule)
            self.assertEqual(uow.events.get(event.id), event)
            self.assertEqual([item.id for item in uow.obligations.list_open(session.id)], [obligation.id])

    def test_seed_db_loads_fixture_data(self) -> None:
        config = self._config()
        fixture_path = Path("tests/fixtures/state/seed_core.json")
        data = json.loads(fixture_path.read_text(encoding="utf-8"))

        with SqliteUnitOfWork(config) as uow:
            seed_db(uow, data)
            uow.commit()

        with SqliteUnitOfWork(config.db_path) as uow:
            self.assertIsNotNone(uow.sessions.get("sess-fixture"))
            self.assertTrue(uow.repo_state.get("sess-fixture").dirty)
            self.assertEqual(uow.obligations.get("obl-fixture").status, ObligationStatus.OPEN)
            self.assertEqual(uow.evidence.get("ev-fixture").metadata["line"], 12)
            self.assertEqual(uow.assertions.get("as-fixture").status, AssertionStatus.SUPPORTED)


if __name__ == "__main__":
    unittest.main()

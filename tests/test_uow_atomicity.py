import sqlite3
import tempfile
import unittest

from egtsr_runtime.config import RuntimeConfig
from egtsr_runtime.db.uow import SqliteUnitOfWork
from egtsr_runtime.enums import ObligationStatus
from egtsr_runtime.models import Evidence, Obligation, Session
from egtsr_runtime.paths import ensure_runtime_dirs


class UnitOfWorkAtomicityTests(unittest.TestCase):
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

    def test_commit_persists_changes(self) -> None:
        config = self._config()
        session = Session(
            id="sess-commit",
            repo_root=config.repo_root,
            branch="main",
            head_hash=None,
            status="active",
            created_at="2026-03-31T11:00:00Z",
            updated_at="2026-03-31T11:00:00Z",
        )

        with SqliteUnitOfWork(config) as uow:
            uow.sessions.create(session)
            uow.commit()

        with SqliteUnitOfWork(config.db_path) as uow:
            self.assertIsNotNone(uow.sessions.get(session.id))

    def test_rollback_prevents_partial_writes(self) -> None:
        config = self._config()
        session = Session(
            id="sess-rollback",
            repo_root=config.repo_root,
            branch="main",
            head_hash=None,
            status="active",
            created_at="2026-03-31T11:10:00Z",
            updated_at="2026-03-31T11:10:00Z",
        )
        obligation = Obligation(
            id="obl-rollback",
            session_id=session.id,
            source="spec",
            statement="Should rollback together",
            status=ObligationStatus.OPEN,
            created_at="2026-03-31T11:11:00Z",
            updated_at="2026-03-31T11:11:00Z",
        )
        invalid_evidence = Evidence(
            id="ev-invalid",
            session_id="missing-session",
            kind="file",
            source_tool="pytest",
            created_at="2026-03-31T11:12:00Z",
        )

        with self.assertRaises(sqlite3.IntegrityError):
            with SqliteUnitOfWork(config) as uow:
                uow.sessions.create(session)
                uow.obligations.upsert(obligation)
                uow.evidence.create(invalid_evidence)
                uow.commit()

        with SqliteUnitOfWork(config.db_path) as uow:
            self.assertIsNone(uow.sessions.get(session.id))
            self.assertIsNone(uow.obligations.get(obligation.id))


if __name__ == "__main__":
    unittest.main()

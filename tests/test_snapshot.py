import json
import tempfile
import unittest
from pathlib import Path

from egtsr_runtime.config import RuntimeConfig
from egtsr_runtime.db.seed import seed_db
from egtsr_runtime.db.uow import SqliteUnitOfWork, load_snapshot, save_snapshot
from egtsr_runtime.models import Capsule, Event, RepoState, Session, SessionSnapshot
from egtsr_runtime.enums import VerifyPhase
from egtsr_runtime.paths import ensure_runtime_dirs


class SnapshotTests(unittest.TestCase):
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

    def test_snapshot_save_and_load_round_trip(self) -> None:
        config = self._config()
        snapshot = SessionSnapshot(
            session=Session(
                id="sess-snap",
                repo_root=config.repo_root,
                branch="feature/snap",
                head_hash="999",
                status="active",
                created_at="2026-03-31T12:00:00Z",
                updated_at="2026-03-31T12:00:00Z",
            ),
            repo_state=RepoState(
                session_id="sess-snap",
                head_hash="999",
                dirty=True,
                changed_files=["src/a.py"],
                last_scan_at="2026-03-31T12:01:00Z",
            ),
            capsules=[
                Capsule(
                    id="cap-snap",
                    session_id="sess-snap",
                    phase=VerifyPhase.TARGETED,
                    frontier_hash="frontier-x",
                    content="snapshot capsule",
                    token_count=21,
                    audit_pass=True,
                    audit_report={"ok": True},
                    created_at="2026-03-31T12:02:00Z",
                )
            ],
            events=[
                Event(
                    id="evt-snap",
                    session_id="sess-snap",
                    event_type="snapshot.saved",
                    payload={"count": 1},
                    created_at="2026-03-31T12:03:00Z",
                )
            ],
        )

        with SqliteUnitOfWork(config) as uow:
            save_snapshot(uow, snapshot)
            uow.commit()

        with SqliteUnitOfWork(config.db_path) as uow:
            loaded = load_snapshot(uow, "sess-snap")

        self.assertEqual(loaded, snapshot)

    def test_snapshot_fixture_seed_can_be_loaded(self) -> None:
        config = self._config()
        data = json.loads(Path("tests/fixtures/state/snapshot_seed.json").read_text(encoding="utf-8"))

        with SqliteUnitOfWork(config) as uow:
            seed_db(uow, data)
            uow.commit()

        with SqliteUnitOfWork(config.db_path) as uow:
            loaded = load_snapshot(uow, "sess-snapshot")

        self.assertIsNotNone(loaded)
        self.assertEqual(len(loaded.capsules), 1)
        self.assertEqual(len(loaded.events), 1)
        self.assertFalse(loaded.repo_state.dirty)


if __name__ == "__main__":
    unittest.main()

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from egtsr_runtime.config import RuntimeConfig
from egtsr_runtime.db.uow import SqliteUnitOfWork
from egtsr_runtime.hooks import parse_hook_stdin
from egtsr_runtime.hooks.session_start import SessionBootstrapService
from egtsr_runtime.paths import ensure_runtime_dirs
from egtsr_runtime.services.repo_inspector import RepoInspectResult


class SessionStartBootstrapTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.paths = ensure_runtime_dirs(self.tmp_dir.name)
        self.config = RuntimeConfig(
            repo_root=self.paths.repo_root,
            egtsr_dir=self.paths.egtsr_dir,
            db_path=self.paths.db_path,
        )
        self.fixtures_dir = Path("tests/fixtures/hooks")

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _fixture_envelope(self, name: str):
        payload = json.loads((self.fixtures_dir / name).read_text(encoding="utf-8"))
        payload["cwd"] = self.paths.repo_root
        return parse_hook_stdin(json.dumps(payload))

    def test_new_session_created_on_startup_source(self) -> None:
        envelope = self._fixture_envelope("session_start_startup.json")

        with SqliteUnitOfWork(self.config) as uow:
            result = SessionBootstrapService(uow, self.paths.raw_events_dir).load_or_create(envelope)

        self.assertTrue(result.is_new_session)
        self.assertFalse(result.safe_resume)

        with SqliteUnitOfWork(self.config.db_path) as uow:
            session = uow.sessions.get(envelope.session_id)
            self.assertIsNotNone(session)
            self.assertEqual(session.repo_root, self.paths.repo_root)
            self.assertEqual(session.status, "active")

    def test_existing_session_loaded_on_resume_source(self) -> None:
        startup_envelope = self._fixture_envelope("session_start_startup.json")
        resume_envelope = self._fixture_envelope("session_start_resume.json")

        with SqliteUnitOfWork(self.config) as uow:
            SessionBootstrapService(uow, self.paths.raw_events_dir).load_or_create(startup_envelope)

        with SqliteUnitOfWork(self.config.db_path) as uow:
            result = SessionBootstrapService(uow, self.paths.raw_events_dir).load_or_create(resume_envelope)

        self.assertFalse(result.is_new_session)
        self.assertTrue(result.safe_resume)

    def test_compact_source_treated_same_as_resume(self) -> None:
        envelope = self._fixture_envelope("session_start_compact.json")

        with SqliteUnitOfWork(self.config) as uow:
            result = SessionBootstrapService(uow, self.paths.raw_events_dir).load_or_create(envelope)

        self.assertTrue(result.safe_resume)

    def test_repo_state_saved_after_bootstrap(self) -> None:
        envelope = self._fixture_envelope("session_start_startup.json")

        with SqliteUnitOfWork(self.config) as uow:
            SessionBootstrapService(uow, self.paths.raw_events_dir).load_or_create(envelope)

        with SqliteUnitOfWork(self.config.db_path) as uow:
            repo_state = uow.repo_state.get(envelope.session_id)
            self.assertIsNotNone(repo_state)
            self.assertEqual(repo_state.session_id, envelope.session_id)
            self.assertEqual(repo_state.changed_files, [])
            self.assertTrue(repo_state.last_scan_at)

    def test_bootstrap_does_not_crash_if_git_not_available(self) -> None:
        envelope = self._fixture_envelope("session_start_startup.json")

        with mock.patch(
            "egtsr_runtime.hooks.session_start.inspect_repo",
            return_value=RepoInspectResult(head_hash=None, dirty=False, branch=None),
        ):
            with SqliteUnitOfWork(self.config) as uow:
                result = SessionBootstrapService(uow, self.paths.raw_events_dir).load_or_create(envelope)

        self.assertIsNone(result.repo_head)
        self.assertIsNone(result.branch)
        self.assertFalse(result.dirty)

    def test_additional_context_generated(self) -> None:
        envelope = self._fixture_envelope("session_start_startup.json")

        with SqliteUnitOfWork(self.config) as uow:
            result = SessionBootstrapService(uow, self.paths.raw_events_dir).load_or_create(envelope)

        self.assertIsNotNone(result.additional_context)
        self.assertIn("session_id=test-session-1", result.additional_context)
        self.assertIn("raw_archive=", result.additional_context)
        archived = list(Path(self.paths.raw_events_dir).glob("*_SessionStart.json"))
        self.assertTrue(archived)


if __name__ == "__main__":
    unittest.main()

"""Tests for repo_state delta updates on PostToolUse (Step 06).

Verifies that when ``enable_reverse_index=True``, PostToolUseService
updates repo_state with changed_files from the normalizer.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from egtsr_runtime.config import RuntimeConfig
from egtsr_runtime.db.uow import SqliteUnitOfWork
from egtsr_runtime.hooks import PostToolUseService, parse_hook_stdin
from egtsr_runtime.models import RepoState, Session
from egtsr_runtime.paths import ensure_runtime_dirs


class TestRepoStateDeltaOnPostToolUse(unittest.TestCase):
    """repo_state is updated after PostToolUse when reverse_index is enabled."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.paths = ensure_runtime_dirs(self.tmp_dir.name)
        self.config = RuntimeConfig(
            repo_root=self.paths.repo_root,
            egtsr_dir=self.paths.egtsr_dir,
            db_path=self.paths.db_path,
            enable_reverse_index=True,
        )
        self.session_id = "test-session-1"
        self.fixtures_dir = Path("tests/fixtures/hooks")

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_edit_sets_repo_state_dirty(self):
        """Edit tool produces changed_files → repo_state.dirty = True."""
        envelope = self._fixture_envelope("post_tool_use_edit.json")

        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow, envelope.session_id)
            PostToolUseService(uow, self.paths.raw_events_dir, self.config).handle(envelope)

        with SqliteUnitOfWork(self.config.db_path) as uow:
            repo_state = uow.repo_state.get(self.session_id)

        self.assertIsNotNone(repo_state)
        self.assertTrue(repo_state.dirty)
        self.assertTrue(len(repo_state.changed_files) > 0)

    def test_write_sets_repo_state_dirty(self):
        """Write tool produces changed_files → repo_state.dirty = True."""
        envelope = self._fixture_envelope("post_tool_use_write.json")

        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow, envelope.session_id)
            PostToolUseService(uow, self.paths.raw_events_dir, self.config).handle(envelope)

        with SqliteUnitOfWork(self.config.db_path) as uow:
            repo_state = uow.repo_state.get(self.session_id)

        self.assertIsNotNone(repo_state)
        self.assertTrue(repo_state.dirty)

    def test_read_does_not_set_dirty(self):
        """Read tool produces no changed_files → repo_state not updated."""
        envelope = self._fixture_envelope("post_tool_use_read.json")

        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow, envelope.session_id)
            PostToolUseService(uow, self.paths.raw_events_dir, self.config).handle(envelope)

        with SqliteUnitOfWork(self.config.db_path) as uow:
            repo_state = uow.repo_state.get(self.session_id)

        # No changed_files from Read → repo_state not created via mark_dirty
        if repo_state is not None:
            self.assertFalse(repo_state.dirty)

    def test_repo_state_upserts_when_no_prior_row(self):
        """mark_dirty upserts even when no prior repo_state row exists."""
        envelope = self._fixture_envelope("post_tool_use_edit.json")

        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow, envelope.session_id)
            # Verify no repo_state row exists
            self.assertIsNone(uow.repo_state.get(self.session_id))
            PostToolUseService(uow, self.paths.raw_events_dir, self.config).handle(envelope)

        with SqliteUnitOfWork(self.config.db_path) as uow:
            repo_state = uow.repo_state.get(self.session_id)

        self.assertIsNotNone(repo_state)
        self.assertTrue(repo_state.dirty)

    def test_repo_state_preserves_head_hash_on_existing_row(self):
        """mark_dirty preserves head_hash when row already exists."""
        envelope = self._fixture_envelope("post_tool_use_edit.json")

        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow, envelope.session_id)
            uow.repo_state.upsert(
                RepoState(
                    session_id=self.session_id,
                    head_hash="original_hash",
                    dirty=False,
                    changed_files=[],
                    last_scan_at="2026-03-31T09:00:00Z",
                )
            )
            uow.commit()

        with SqliteUnitOfWork(self.config.db_path) as uow:
            self._seed_session(uow, envelope.session_id)
            PostToolUseService(uow, self.paths.raw_events_dir, self.config).handle(envelope)

        with SqliteUnitOfWork(self.config.db_path) as uow:
            repo_state = uow.repo_state.get(self.session_id)

        self.assertIsNotNone(repo_state)
        self.assertTrue(repo_state.dirty)
        self.assertEqual(repo_state.head_hash, "original_hash")

    def test_session_frontier_updated_on_repo_state_change(self):
        """on_repo_state_change increments session_frontier version."""
        envelope = self._fixture_envelope("post_tool_use_edit.json")

        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow, envelope.session_id)
            PostToolUseService(uow, self.paths.raw_events_dir, self.config).handle(envelope)

        with SqliteUnitOfWork(self.config.db_path) as uow:
            sf = uow.session_frontier.get(self.session_id)

        self.assertIsNotNone(sf)
        self.assertGreaterEqual(sf.frontier_version, 1)

    def test_legacy_mode_does_not_update_repo_state(self):
        """When enable_reverse_index=False, repo_state is not updated."""
        legacy_config = RuntimeConfig(
            repo_root=self.paths.repo_root,
            egtsr_dir=self.paths.egtsr_dir,
            db_path=self.paths.db_path,
            enable_reverse_index=False,
        )
        envelope = self._fixture_envelope("post_tool_use_edit.json")

        with SqliteUnitOfWork(legacy_config) as uow:
            self._seed_session(uow, envelope.session_id)
            PostToolUseService(uow, self.paths.raw_events_dir, legacy_config).handle(envelope)

        with SqliteUnitOfWork(legacy_config.db_path) as uow:
            repo_state = uow.repo_state.get(self.session_id)

        # Legacy mode: no repo_state delta update
        self.assertIsNone(repo_state)

    def _fixture_envelope(self, name: str):
        payload = json.loads((self.fixtures_dir / name).read_text(encoding="utf-8"))
        payload["cwd"] = self.paths.repo_root
        return parse_hook_stdin(json.dumps(payload))

    def _seed_session(self, uow: SqliteUnitOfWork, session_id: str) -> None:
        if uow.sessions.get(session_id) is not None:
            return
        uow.sessions.create(
            Session(
                id=session_id,
                repo_root=self.paths.repo_root,
                branch="main",
                head_hash="abc123",
                status="active",
                created_at="2026-03-31T10:00:00Z",
                updated_at="2026-03-31T10:00:00Z",
            )
        )


if __name__ == "__main__":
    unittest.main()

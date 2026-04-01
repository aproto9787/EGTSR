from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from egtsr_runtime.config import RuntimeConfig
from egtsr_runtime.db.uow import SqliteUnitOfWork
from egtsr_runtime.hooks import UserPromptSubmitService, parse_hook_stdin
from egtsr_runtime.models import Session
from egtsr_runtime.models.freshness import (
    FreshnessDiff,
    FreshnessFrontier,
    compute_changed_files_fingerprint,
    compute_freshness_diff,
)
from egtsr_runtime.paths import ensure_runtime_dirs
from egtsr_runtime.services.freshness_gate import FreshnessGateService


class FreshnessModelTests(unittest.TestCase):
    """FreshnessFrontier / FreshnessDiff 단위 테스트."""

    def test_no_mismatch_for_identical_frontiers(self) -> None:
        a = FreshnessFrontier(
            session_id="s1",
            repo_hash="h1",
            branch="main",
            head_hash="abc",
            dirty=False,
            changed_files_fingerprint="fp1",
            live_ticket_ids=["t1"],
            open_obligation_ids=["o1"],
        )
        b = FreshnessFrontier(
            session_id="s1",
            repo_hash="h1",
            branch="main",
            head_hash="abc",
            dirty=False,
            changed_files_fingerprint="fp1",
            live_ticket_ids=["t1"],
            open_obligation_ids=["o1"],
        )
        diff = compute_freshness_diff(a, b)
        self.assertFalse(diff.has_mismatch)
        self.assertFalse(diff.head_changed)
        self.assertFalse(diff.branch_changed)
        self.assertFalse(diff.dirty_changed)
        self.assertFalse(diff.files_changed)
        self.assertEqual(diff.new_tickets, [])
        self.assertEqual(diff.new_obligations, [])

    def test_head_changed(self) -> None:
        a = FreshnessFrontier(head_hash="aaa")
        b = FreshnessFrontier(head_hash="bbb")
        diff = compute_freshness_diff(a, b)
        self.assertTrue(diff.has_mismatch)
        self.assertTrue(diff.head_changed)

    def test_branch_changed(self) -> None:
        a = FreshnessFrontier(branch="main")
        b = FreshnessFrontier(branch="feature")
        diff = compute_freshness_diff(a, b)
        self.assertTrue(diff.has_mismatch)
        self.assertTrue(diff.branch_changed)

    def test_dirty_changed(self) -> None:
        a = FreshnessFrontier(dirty=False)
        b = FreshnessFrontier(dirty=True)
        diff = compute_freshness_diff(a, b)
        self.assertTrue(diff.has_mismatch)
        self.assertTrue(diff.dirty_changed)

    def test_files_changed(self) -> None:
        a = FreshnessFrontier(changed_files_fingerprint="fp1")
        b = FreshnessFrontier(changed_files_fingerprint="fp2")
        diff = compute_freshness_diff(a, b)
        self.assertTrue(diff.has_mismatch)
        self.assertTrue(diff.files_changed)

    def test_new_tickets_detected(self) -> None:
        a = FreshnessFrontier(live_ticket_ids=["t1"])
        b = FreshnessFrontier(live_ticket_ids=["t1", "t2"])
        diff = compute_freshness_diff(a, b)
        self.assertTrue(diff.has_mismatch)
        self.assertEqual(diff.new_tickets, ["t2"])

    def test_new_obligations_detected(self) -> None:
        a = FreshnessFrontier(open_obligation_ids=["o1"])
        b = FreshnessFrontier(open_obligation_ids=["o1", "o2"])
        diff = compute_freshness_diff(a, b)
        self.assertTrue(diff.has_mismatch)
        self.assertEqual(diff.new_obligations, ["o2"])

    def test_fingerprint_deterministic(self) -> None:
        files = ["b.py", "a.py", "c.py"]
        fp1 = compute_changed_files_fingerprint(files)
        fp2 = compute_changed_files_fingerprint(["a.py", "c.py", "b.py"])
        self.assertEqual(fp1, fp2)

    def test_fingerprint_changes_with_different_files(self) -> None:
        fp1 = compute_changed_files_fingerprint(["a.py"])
        fp2 = compute_changed_files_fingerprint(["b.py"])
        self.assertNotEqual(fp1, fp2)


class FreshnessRepositoryTests(unittest.TestCase):
    """SqliteFreshnessRepository DB 테스트."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.paths = ensure_runtime_dirs(self.tmp_dir.name)
        self.config = RuntimeConfig(
            repo_root=self.paths.repo_root,
            egtsr_dir=self.paths.egtsr_dir,
            db_path=self.paths.db_path,
        )

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_save_and_get_latest(self) -> None:
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            frontier = FreshnessFrontier(
                session_id="sess-fresh",
                repo_hash="hash1",
                branch="main",
                head_hash="abc",
                dirty=False,
                changed_files_fingerprint="fp",
                live_ticket_ids=["t1"],
                open_obligation_ids=["o1"],
                capsule_id="cap1",
                source="session_start",
                created_at="2026-04-01T10:00:00Z",
            )
            row_id = uow.freshness_repo.save(frontier)
            uow.commit()

        self.assertIsNotNone(row_id)

        with SqliteUnitOfWork(self.config) as uow:
            loaded = uow.freshness_repo.get_latest("sess-fresh")

        self.assertIsNotNone(loaded)
        self.assertEqual(loaded.session_id, "sess-fresh")
        self.assertEqual(loaded.branch, "main")
        self.assertEqual(loaded.head_hash, "abc")
        self.assertFalse(loaded.dirty)
        self.assertEqual(loaded.live_ticket_ids, ["t1"])
        self.assertEqual(loaded.open_obligation_ids, ["o1"])
        self.assertEqual(loaded.source, "session_start")

    def test_get_latest_by_source(self) -> None:
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            uow.freshness_repo.save(
                FreshnessFrontier(
                    session_id="sess-fresh",
                    repo_hash="h1",
                    source="session_start",
                    created_at="2026-04-01T10:00:00Z",
                )
            )
            uow.freshness_repo.save(
                FreshnessFrontier(
                    session_id="sess-fresh",
                    repo_hash="h2",
                    source="user_prompt_submit",
                    created_at="2026-04-01T10:01:00Z",
                )
            )
            uow.commit()

        with SqliteUnitOfWork(self.config) as uow:
            ss = uow.freshness_repo.get_latest_by_source("sess-fresh", "session_start")
            ups = uow.freshness_repo.get_latest_by_source(
                "sess-fresh", "user_prompt_submit"
            )

        self.assertEqual(ss.repo_hash, "h1")
        self.assertEqual(ups.repo_hash, "h2")

    def test_get_latest_returns_none_for_unknown_session(self) -> None:
        with SqliteUnitOfWork(self.config) as uow:
            result = uow.freshness_repo.get_latest("nonexistent")
        self.assertIsNone(result)

    def _seed_session(self, uow: SqliteUnitOfWork) -> None:
        uow.sessions.create(
            Session(
                id="sess-fresh",
                repo_root=self.paths.repo_root,
                branch="main",
                head_hash="abc",
                status="active",
                created_at="2026-04-01T09:00:00Z",
                updated_at="2026-04-01T09:00:00Z",
            )
        )


class FreshnessGateServiceTests(unittest.TestCase):
    """FreshnessGateService 통합 테스트."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.paths = ensure_runtime_dirs(self.tmp_dir.name)
        self.config = RuntimeConfig(
            repo_root=self.paths.repo_root,
            egtsr_dir=self.paths.egtsr_dir,
            db_path=self.paths.db_path,
        )

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    @mock.patch("egtsr_runtime.services.freshness_gate.inspect_repo")
    def test_collect_frontier_stores_to_db(self, mock_inspect) -> None:
        mock_inspect.return_value = mock.MagicMock(
            head_hash="abc123", dirty=False, branch="main"
        )
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow, "sess-fg")
            gate = FreshnessGateService(uow, self.tmp_dir.name)
            with mock.patch.object(gate, "_get_changed_files", return_value=[]):
                frontier = gate.collect_frontier("sess-fg", "session_start")
            uow.commit()

        self.assertIsNotNone(frontier.id)
        self.assertEqual(frontier.session_id, "sess-fg")
        self.assertEqual(frontier.head_hash, "abc123")
        self.assertEqual(frontier.source, "session_start")

    @mock.patch("egtsr_runtime.services.freshness_gate.inspect_repo")
    def test_check_freshness_no_mismatch(self, mock_inspect) -> None:
        mock_inspect.return_value = mock.MagicMock(
            head_hash="abc123", dirty=False, branch="main"
        )
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow, "sess-fg")
            gate = FreshnessGateService(uow, self.tmp_dir.name)
            with mock.patch.object(gate, "_get_changed_files", return_value=[]):
                gate.collect_frontier("sess-fg", "session_start")
                diff = gate.check_freshness("sess-fg")
            uow.commit()

        self.assertFalse(diff.has_mismatch)

    @mock.patch("egtsr_runtime.services.freshness_gate.inspect_repo")
    def test_check_freshness_detects_head_change(self, mock_inspect) -> None:
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow, "sess-fg")
            gate = FreshnessGateService(uow, self.tmp_dir.name)

            # First call: session_start
            mock_inspect.return_value = mock.MagicMock(
                head_hash="abc123", dirty=False, branch="main"
            )
            with mock.patch.object(gate, "_get_changed_files", return_value=[]):
                gate.collect_frontier("sess-fg", "session_start")

            # Second call: head changed
            mock_inspect.return_value = mock.MagicMock(
                head_hash="def456", dirty=False, branch="main"
            )
            with mock.patch.object(gate, "_get_changed_files", return_value=[]):
                diff = gate.check_freshness("sess-fg")

            uow.commit()

        self.assertTrue(diff.has_mismatch)
        self.assertTrue(diff.head_changed)

    def test_describe_mismatch(self) -> None:
        diff = FreshnessDiff(
            head_changed=True,
            dirty_changed=True,
            has_mismatch=True,
        )
        desc = FreshnessGateService.describe_mismatch(diff)
        self.assertIn("head changed", desc)
        self.assertIn("dirty state changed", desc)

    def test_describe_no_mismatch(self) -> None:
        diff = FreshnessDiff()
        desc = FreshnessGateService.describe_mismatch(diff)
        self.assertEqual(desc, "no mismatch")

    def _seed_session(self, uow: SqliteUnitOfWork, session_id: str) -> None:
        uow.sessions.create(
            Session(
                id=session_id,
                repo_root=self.paths.repo_root,
                branch="main",
                head_hash="abc123",
                status="active",
                created_at="2026-04-01T09:00:00Z",
                updated_at="2026-04-01T09:00:00Z",
            )
        )


class UserPromptSubmitFreshnessBlockTests(unittest.TestCase):
    """user_prompt_submit에서 freshness mismatch 시 block 테스트."""

    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.paths = ensure_runtime_dirs(self.tmp_dir.name)
        self.config = RuntimeConfig(
            repo_root=self.paths.repo_root,
            egtsr_dir=self.paths.egtsr_dir,
            db_path=self.paths.db_path,
        )
        self.session_id = "sess-fresh-block"

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    @mock.patch("egtsr_runtime.hooks.user_prompt_submit.FreshnessGateService")
    def test_write_prompt_blocked_on_freshness_mismatch(self, MockGate) -> None:
        """write-risk prompt + freshness mismatch → block."""
        mock_gate = MockGate.return_value
        mock_gate.check_freshness.return_value = FreshnessDiff(
            head_changed=True,
            has_mismatch=True,
        )
        MockGate.describe_mismatch.return_value = "head changed since session start"

        envelope = self._envelope(prompt="fix the bug")

        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            result = UserPromptSubmitService(
                uow, self.config, self.paths.raw_events_dir
            ).handle(envelope)

        self.assertFalse(result.allowed)
        self.assertEqual(result.response["decision"], "block")
        self.assertIn("Freshness mismatch", result.response["reason"])

    @mock.patch("egtsr_runtime.hooks.user_prompt_submit.FreshnessGateService")
    def test_read_prompt_allowed_despite_freshness_mismatch(self, MockGate) -> None:
        """read-only prompt + freshness mismatch → allow (no block)."""
        mock_gate = MockGate.return_value
        mock_gate.check_freshness.return_value = FreshnessDiff(
            head_changed=True,
            has_mismatch=True,
        )

        envelope = self._envelope(prompt="read the file")

        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            result = UserPromptSubmitService(
                uow, self.config, self.paths.raw_events_dir
            ).handle(envelope)

        # Read prompts should pass through freshness gate
        self.assertTrue(result.allowed)

    @mock.patch("egtsr_runtime.hooks.user_prompt_submit.FreshnessGateService")
    def test_no_block_when_no_mismatch(self, MockGate) -> None:
        """no mismatch → normal flow (allow if audit passes)."""
        mock_gate = MockGate.return_value
        mock_gate.check_freshness.return_value = FreshnessDiff()

        envelope = self._envelope(prompt="fix the bug")

        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            result = UserPromptSubmitService(
                uow, self.config, self.paths.raw_events_dir
            ).handle(envelope)

        # No freshness block — proceeds to capsule compile
        # (may still block due to audit, but not freshness)
        self.assertNotIn("Freshness mismatch", result.response.get("reason", ""))

    def _envelope(self, *, prompt: str, source: str = "startup"):
        return parse_hook_stdin(
            json.dumps(
                {
                    "session_id": self.session_id,
                    "cwd": self.paths.repo_root,
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": prompt,
                    "source": source,
                }
            )
        )

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
                created_at="2026-04-01T09:00:00Z",
                updated_at="2026-04-01T09:00:00Z",
            )
        )


if __name__ == "__main__":
    unittest.main()

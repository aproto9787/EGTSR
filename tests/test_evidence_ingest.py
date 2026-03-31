from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from egtsr_runtime.config import RuntimeConfig
from egtsr_runtime.db.uow import SqliteUnitOfWork
from egtsr_runtime.hooks import PostToolUseService, parse_hook_stdin
from egtsr_runtime.ingest import MAX_EXCERPT_LENGTH
from egtsr_runtime.models import Session
from egtsr_runtime.paths import ensure_runtime_dirs


class TestEvidenceIngest(unittest.TestCase):
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

    def test_read_evidence_stored(self):
        envelope = self._fixture_envelope("post_tool_use_read.json")
        result = self._handle(envelope)
        evidence = self._get_evidence(result.evidence_ids[0])

        self.assertEqual(evidence.kind, "read_span")
        self.assertEqual(evidence.polarity, "positive")
        self.assertEqual(evidence.source_tool, "Read")
        self.assertEqual(evidence.path, "/repo/auth/session.py")
        self.assertEqual(evidence.scope_kind, "file")

    def test_bash_evidence_stored(self):
        envelope = self._fixture_envelope("post_tool_use_bash.json")
        result = self._handle(envelope)
        evidence = self._get_evidence(result.evidence_ids[0])

        self.assertEqual(evidence.kind, "bash_output")
        self.assertEqual(evidence.source_tool, "Bash")
        self.assertEqual(evidence.scope_kind, "command")
        self.assertEqual(evidence.polarity, "positive")

    def test_test_evidence_stored(self):
        envelope = self._fixture_envelope("post_tool_use_test.json")
        result = self._handle(envelope)
        evidence = self._get_evidence(result.evidence_ids[0])

        self.assertEqual(evidence.kind, "test_output")
        self.assertEqual(evidence.source_tool, "Test")
        self.assertEqual(evidence.polarity, "positive")

    def test_bash_fail_negative_polarity(self):
        envelope = self._fixture_envelope("post_tool_use_bash_fail.json")
        result = self._handle(envelope)
        evidence = self._get_evidence(result.evidence_ids[0])

        self.assertEqual(evidence.polarity, "negative")

    def test_write_evidence_and_changed_files(self):
        envelope = self._fixture_envelope("post_tool_use_write.json")
        result = self._handle(envelope)
        evidence = self._get_evidence(result.evidence_ids[0])

        self.assertEqual(evidence.kind, "diff_meta")
        self.assertEqual(result.changed_files, ["/repo/src/main.py"])
        self.assertEqual(evidence.metadata["changed_files"], ["/repo/src/main.py"])

    def test_edit_evidence_and_changed_files(self):
        envelope = self._fixture_envelope("post_tool_use_edit.json")
        result = self._handle(envelope)
        evidence = self._get_evidence(result.evidence_ids[0])

        self.assertEqual(evidence.kind, "diff_meta")
        self.assertEqual(result.changed_files, ["/repo/src/utils.py"])
        self.assertEqual(evidence.metadata["changed_files"], ["/repo/src/utils.py"])

    def test_raw_archive_only_verbose(self):
        long_tail = "TAIL-MARKER"
        payload = {
            "session_id": "test-session-1",
            "cwd": self.paths.repo_root,
            "hook_event_name": "PostToolUse",
            "tool_name": "Bash",
            "tool_input": {"command": "pytest -q"},
            "tool_response": {
                "stdout": "summary\n" + ("1234567890" * 60) + long_tail,
                "stderr": "",
                "exit_code": 0,
            },
            "tool_use_id": "toolu_verbose_1",
        }
        envelope = parse_hook_stdin(json.dumps(payload))
        result = self._handle(envelope)
        evidence = self._get_evidence(result.evidence_ids[0])
        event = self._latest_event()
        archived_text = Path(event.payload["raw_archive_path"]).read_text(encoding="utf-8")

        self.assertIn(long_tail, archived_text)
        self.assertNotIn(long_tail, evidence.excerpt)

    def test_state_delta_after_ingest(self):
        envelope = self._fixture_envelope("post_tool_use_bash.json")

        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow, envelope.session_id)
            before = len(uow.evidence.list_for_session(envelope.session_id))
            PostToolUseService(uow, self.paths.raw_events_dir).handle(envelope)

        with SqliteUnitOfWork(self.config.db_path) as uow:
            after = len(uow.evidence.list_for_session(envelope.session_id))

        self.assertEqual(after, before + 1)

    def test_event_logged(self):
        envelope = self._fixture_envelope("post_tool_use_read.json")
        self._handle(envelope)
        event = self._latest_event()

        self.assertEqual(event.event_type, "post_tool_use.ingested")
        self.assertEqual(event.payload["tool_name"], "Read")
        self.assertTrue(Path(event.payload["raw_archive_path"]).exists())

    def test_excerpt_clipped(self):
        payload = {
            "session_id": "test-session-1",
            "cwd": self.paths.repo_root,
            "hook_event_name": "PostToolUse",
            "tool_name": "Read",
            "tool_input": {"file_path": "/repo/README.md"},
            "tool_response": {"content": "x" * (MAX_EXCERPT_LENGTH + 50)},
            "tool_use_id": "toolu_read_long",
        }
        envelope = parse_hook_stdin(json.dumps(payload))
        result = self._handle(envelope)
        evidence = self._get_evidence(result.evidence_ids[0])

        self.assertEqual(len(evidence.excerpt), MAX_EXCERPT_LENGTH)
        self.assertTrue(evidence.excerpt.endswith("..."))

    def test_unknown_tool_handled(self):
        payload = {
            "session_id": "test-session-1",
            "cwd": self.paths.repo_root,
            "hook_event_name": "PostToolUse",
            "tool_name": "UnknownTool",
            "tool_input": {"file_path": "/repo/misc.txt"},
            "tool_response": {"message": "done"},
            "tool_use_id": "toolu_unknown_1",
        }
        envelope = parse_hook_stdin(json.dumps(payload))
        result = self._handle(envelope)
        evidence = self._get_evidence(result.evidence_ids[0])

        self.assertEqual(len(result.evidence_ids), 1)
        self.assertEqual(evidence.kind, "tool_output")
        self.assertEqual(evidence.source_tool, "UnknownTool")

    def _fixture_envelope(self, name: str):
        payload = json.loads((self.fixtures_dir / name).read_text(encoding="utf-8"))
        payload["cwd"] = self.paths.repo_root
        return parse_hook_stdin(json.dumps(payload))

    def _handle(self, envelope):
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow, envelope.session_id)
            return PostToolUseService(uow, self.paths.raw_events_dir).handle(envelope)

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

    def _get_evidence(self, evidence_id: str):
        with SqliteUnitOfWork(self.config.db_path) as uow:
            evidence = uow.evidence.get(evidence_id)
        self.assertIsNotNone(evidence)
        return evidence

    def _latest_event(self):
        with SqliteUnitOfWork(self.config.db_path) as uow:
            events = uow.events.list_for_session("test-session-1")
        self.assertTrue(events)
        return events[-1]


if __name__ == "__main__":
    unittest.main()

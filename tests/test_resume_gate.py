from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from egtsr_runtime.config import RuntimeConfig
from egtsr_runtime.db.uow import SqliteUnitOfWork, load_snapshot
from egtsr_runtime.enums import AssertionStatus, InvalidationStatus, ObligationStatus, VerifyPhase
from egtsr_runtime.hooks import SessionEndService, UserPromptSubmitService, parse_hook_stdin
from egtsr_runtime.hooks.session_start import SessionBootstrapService
from egtsr_runtime.models import Assertion, Capsule, Evidence, Event, InvalidationTicket, Obligation, RepoState, Session
from egtsr_runtime.paths import ensure_runtime_dirs


class TestResumeGate(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.paths = ensure_runtime_dirs(self.tmp_dir.name)
        self.config = RuntimeConfig(
            repo_root=self.paths.repo_root,
            egtsr_dir=self.paths.egtsr_dir,
            db_path=self.paths.db_path,
        )
        self.resume_fixtures = Path("tests/fixtures/resume")
        self.hook_fixtures = Path("tests/fixtures/hooks")

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_resume_edit_blocked(self):
        start_envelope = self._fixture_envelope(self.resume_fixtures, "resume_edit_blocked.json")
        edit_envelope = self._prompt_envelope("fix the failing test", source="resume")

        with SqliteUnitOfWork(self.config) as uow:
            self._seed_allow_state(uow, session_id=start_envelope.session_id)
            SessionBootstrapService(uow, self.paths.raw_events_dir).load_or_create(start_envelope)

        with SqliteUnitOfWork(self.config.db_path) as uow:
            result = UserPromptSubmitService(uow, self.config, self.paths.raw_events_dir).handle(edit_envelope)

        self.assertFalse(result.allowed)
        self.assertEqual(result.response["decision"], "block")
        self.assertIn("Resume gate active", result.response["reason"])

    def test_resume_read_allowed(self):
        start_envelope = self._fixture_envelope(self.resume_fixtures, "resume_edit_blocked.json")
        read_envelope = self._fixture_envelope(self.resume_fixtures, "resume_read_allowed.json")

        with SqliteUnitOfWork(self.config) as uow:
            self._seed_allow_state(uow, session_id=start_envelope.session_id)
            SessionBootstrapService(uow, self.paths.raw_events_dir).load_or_create(start_envelope)

        with SqliteUnitOfWork(self.config.db_path) as uow:
            result = UserPromptSubmitService(uow, self.config, self.paths.raw_events_dir).handle(read_envelope)

        self.assertTrue(result.allowed)
        self.assertEqual(result.intent, "read")

    def test_resume_inspect_allowed(self):
        start_envelope = self._fixture_envelope(self.resume_fixtures, "resume_edit_blocked.json")
        inspect_envelope = self._prompt_envelope("inspect the current hook state", source="resume")

        with SqliteUnitOfWork(self.config) as uow:
            self._seed_allow_state(uow, session_id=start_envelope.session_id)
            SessionBootstrapService(uow, self.paths.raw_events_dir).load_or_create(start_envelope)

        with SqliteUnitOfWork(self.config.db_path) as uow:
            result = UserPromptSubmitService(uow, self.config, self.paths.raw_events_dir).handle(inspect_envelope)

        self.assertTrue(result.allowed)
        self.assertEqual(result.intent, "inspect")

    def test_resume_test_allowed(self):
        start_envelope = self._fixture_envelope(self.resume_fixtures, "resume_edit_blocked.json")
        test_envelope = self._prompt_envelope("run test coverage", source="resume")

        with SqliteUnitOfWork(self.config) as uow:
            self._seed_allow_state(uow, session_id=start_envelope.session_id)
            SessionBootstrapService(uow, self.paths.raw_events_dir).load_or_create(start_envelope)

        with SqliteUnitOfWork(self.config.db_path) as uow:
            result = UserPromptSubmitService(uow, self.config, self.paths.raw_events_dir).handle(test_envelope)

        self.assertTrue(result.allowed)
        self.assertEqual(result.intent, "test")

    def test_compact_same_as_resume(self):
        envelope = self._fixture_envelope(self.resume_fixtures, "compact_start.json")

        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow, session_id=envelope.session_id)
            result = SessionBootstrapService(uow, self.paths.raw_events_dir).load_or_create(envelope)

        self.assertTrue(result.safe_resume)
        gate_data = json.loads(Path(self.paths.resume_gate_path).read_text(encoding="utf-8"))
        self.assertTrue(gate_data["edit_blocked"])

    def test_db_corruption_fallback(self):
        envelope = self._fixture_envelope(self.resume_fixtures, "db_corruption.json")

        with SqliteUnitOfWork(self.config) as uow:
            self._seed_allow_state(uow, session_id=envelope.session_id)
            service = UserPromptSubmitService(uow, self.config, self.paths.raw_events_dir)
            with mock.patch.object(uow.repo_state, "get", side_effect=sqlite3.DatabaseError("corrupt")):
                result = service.handle(envelope)

        self.assertFalse(result.allowed)
        self.assertEqual(result.response["decision"], "block")
        self.assertIn("db_health_check_failed", result.response["reason"])

    def test_startup_no_block(self):
        envelope = self._prompt_envelope("fix the failing retry logic", source="startup")

        with SqliteUnitOfWork(self.config) as uow:
            self._seed_allow_state(uow, session_id=envelope.session_id)
            result = UserPromptSubmitService(uow, self.config, self.paths.raw_events_dir).handle(envelope)

        self.assertTrue(result.allowed)
        self.assertEqual(result.intent, "edit")

    def test_dirty_repo_blocks_edit(self):
        envelope = self._prompt_envelope("fix the dirty repo issue", source="startup")

        with SqliteUnitOfWork(self.config) as uow:
            self._seed_allow_state(uow, session_id=envelope.session_id, repo_dirty=True)
            result = UserPromptSubmitService(uow, self.config, self.paths.raw_events_dir).handle(envelope)

        self.assertFalse(result.allowed)
        self.assertIn("repo_dirty", result.response["reason"])

    def test_live_tickets_block_edit(self):
        envelope = self._prompt_envelope("implement the pending patch", source="startup")

        with SqliteUnitOfWork(self.config) as uow:
            self._seed_allow_state(uow, session_id=envelope.session_id)
            self._seed_live_ticket(uow, session_id=envelope.session_id)
            result = UserPromptSubmitService(uow, self.config, self.paths.raw_events_dir).handle(envelope)

        self.assertFalse(result.allowed)
        self.assertIn("live_tickets=1", result.response["reason"])

    def test_last_good_capsule_saved(self):
        envelope = self._fixture_envelope(self.hook_fixtures, "session_end.json")

        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session_end_state(uow, session_id=envelope.session_id)
            SessionEndService(uow, self.paths, self.paths.raw_events_dir).handle(envelope)

        payload = json.loads(Path(self.paths.last_good_capsule_path).read_text(encoding="utf-8"))
        self.assertEqual(payload["compiled_at"], "2026-03-31T11:00:00Z")
        self.assertEqual(payload["token_estimate"], 42)
        self.assertEqual(payload["open_obligation_ids"], [])
        self.assertEqual(payload["blocking_rechecks"], [])
        self.assertEqual(payload["phase"], "decision")

    def test_resume_gate_json_saved(self):
        envelope = self._fixture_envelope(self.hook_fixtures, "session_end.json")

        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session_end_state(uow, session_id=envelope.session_id, live_ticket=True)
            SessionEndService(uow, self.paths, self.paths.raw_events_dir).handle(envelope)

        payload = json.loads(Path(self.paths.resume_gate_path).read_text(encoding="utf-8"))
        self.assertEqual(payload["session_id"], envelope.session_id)
        self.assertTrue(payload["edit_blocked"])

    def test_session_end_snapshot_saved(self):
        envelope = self._fixture_envelope(self.hook_fixtures, "session_end.json")

        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session_end_state(uow, session_id=envelope.session_id)
            SessionEndService(uow, self.paths, self.paths.raw_events_dir).handle(envelope)

        with SqliteUnitOfWork(self.config.db_path) as uow:
            snapshot = load_snapshot(uow, envelope.session_id)

        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot.session.id, envelope.session_id)
        self.assertTrue(any(event.event_type == "session_end.handled" for event in snapshot.events))

    def _fixture_envelope(self, base_dir: Path, name: str):
        payload = json.loads((base_dir / name).read_text(encoding="utf-8"))
        payload["cwd"] = self.paths.repo_root
        return parse_hook_stdin(json.dumps(payload))

    def _prompt_envelope(self, prompt: str, source: str = "startup", session_id: str = "resume-session-1"):
        return parse_hook_stdin(
            json.dumps(
                {
                    "session_id": session_id,
                    "cwd": self.paths.repo_root,
                    "hook_event_name": "UserPromptSubmit",
                    "prompt": prompt,
                    "source": source,
                }
            )
        )

    def _seed_allow_state(self, uow: SqliteUnitOfWork, session_id: str, repo_dirty: bool = False) -> None:
        self._seed_session(uow, session_id=session_id, repo_dirty=repo_dirty)
        obligation = Obligation(
            id=f"obl-{session_id}",
            session_id=session_id,
            source="spec",
            statement="Need supported evidence",
            priority=10,
            status=ObligationStatus.OPEN,
            created_at="2026-03-31T10:00:00Z",
            updated_at="2026-03-31T10:00:00Z",
        )
        evidence = Evidence(
            id=f"ev-{session_id}",
            session_id=session_id,
            kind="command",
            source_tool="pytest",
            path="tests/test_resume_gate.py",
            polarity="positive",
            excerpt="supported evidence",
            created_at="2026-03-31T10:01:00Z",
        )
        assertion = Assertion(
            id=f"as-{session_id}",
            session_id=session_id,
            obligation_id=obligation.id,
            statement="Supported assertion",
            status=AssertionStatus.SUPPORTED,
            confidence=0.9,
            evidence_ids=[evidence.id],
            created_at="2026-03-31T10:02:00Z",
            updated_at="2026-03-31T10:02:00Z",
        )
        uow.obligations.upsert(obligation)
        uow.evidence.create(evidence)
        uow.assertions.upsert(assertion)

    def _seed_session(self, uow: SqliteUnitOfWork, session_id: str, repo_dirty: bool = False) -> None:
        if uow.sessions.get(session_id) is None:
            uow.sessions.create(
                Session(
                    id=session_id,
                    repo_root=self.paths.repo_root,
                    branch="main",
                    head_hash="abc123",
                    status="active",
                    created_at="2026-03-31T09:59:00Z",
                    updated_at="2026-03-31T09:59:00Z",
                )
            )
        uow.repo_state.upsert(
            RepoState(
                session_id=session_id,
                head_hash="abc123",
                dirty=repo_dirty,
                changed_files=["src/runtime.py"] if repo_dirty else [],
                last_scan_at="2026-03-31T10:00:00Z",
            )
        )

    def _seed_live_ticket(self, uow: SqliteUnitOfWork, session_id: str) -> None:
        uow.invalidations.upsert(
            InvalidationTicket(
                id=f"inv-{session_id}",
                session_id=session_id,
                subject_type="assertion",
                subject_id=f"as-{session_id}",
                trigger_kind="file_change",
                trigger_ref="src/runtime.py",
                status=InvalidationStatus.LIVE,
                metadata={"reason": "stale"},
                created_at="2026-03-31T10:05:00Z",
                updated_at="2026-03-31T10:05:00Z",
            )
        )

    def _seed_session_end_state(self, uow: SqliteUnitOfWork, session_id: str, live_ticket: bool = False) -> None:
        self._seed_session(uow, session_id=session_id)
        uow.capsules.create(
            Capsule(
                id="cap-session-end",
                session_id=session_id,
                phase=VerifyPhase.DECISION,
                frontier_hash="frontier-end",
                content="final capsule",
                token_count=42,
                audit_pass=True,
                audit_report={"passed": True},
                created_at="2026-03-31T11:00:00Z",
            )
        )
        uow.events.create(
            Event(
                id="evt-before-end",
                session_id=session_id,
                event_type="session.bootstrap",
                payload={"ok": True},
                created_at="2026-03-31T10:30:00Z",
            )
        )
        if live_ticket:
            self._seed_live_ticket(uow, session_id=session_id)


if __name__ == "__main__":
    unittest.main()

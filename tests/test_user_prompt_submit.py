from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from egtsr_runtime.config import RuntimeConfig
from egtsr_runtime.db.uow import SqliteUnitOfWork
from egtsr_runtime.enums import AssertionStatus, ObligationStatus, VerifyPhase
from egtsr_runtime.hooks import UserPromptSubmitService, parse_hook_stdin
from egtsr_runtime.models import Assertion, Evidence, Obligation, Session
from egtsr_runtime.paths import ensure_runtime_dirs


class UserPromptSubmitServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.paths = ensure_runtime_dirs(self.tmp_dir.name)
        self.config = RuntimeConfig(
            repo_root=self.paths.repo_root,
            egtsr_dir=self.paths.egtsr_dir,
            db_path=self.paths.db_path,
        )
        self.session_id = "sess-user-prompt"

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def test_allow_path_when_audit_passes(self) -> None:
        envelope = self._envelope(prompt="read the file")

        with SqliteUnitOfWork(self.config) as uow:
            self._seed_allow_state(uow)
            result = UserPromptSubmitService(uow, self.config, self.paths.raw_events_dir).handle(envelope)

        self.assertTrue(result.allowed)
        self.assertNotIn("decision", result.response)
        self.assertEqual(result.response["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertEqual(result.intent, "read")
        self.assertTrue(result.audit_report.passed)

    def test_block_path_when_audit_fails(self) -> None:
        envelope = self._envelope(prompt="fix the bug")

        with SqliteUnitOfWork(self.config) as uow:
            self._seed_block_state(uow)
            result = UserPromptSubmitService(uow, self.config, self.paths.raw_events_dir).handle(envelope)

        self.assertFalse(result.allowed)
        self.assertEqual(result.response["decision"], "block")
        self.assertIn("Unsupported confirmed assertions", result.response["reason"])
        self.assertFalse(result.audit_report.passed)

    def test_fail_closed_when_compiler_crashes_outside_resume(self) -> None:
        """v0.2: user_prompt_submit is always fail-closed, even outside resume."""
        envelope = self._envelope(prompt="read the file", source="startup")

        with SqliteUnitOfWork(self.config) as uow:
            self._seed_allow_state(uow)
            service = UserPromptSubmitService(uow, self.config, self.paths.raw_events_dir)
            with mock.patch.object(service._compiler, "compile", side_effect=RuntimeError("boom")):
                result = service.handle(envelope)

        self.assertFalse(result.allowed)
        self.assertEqual(result.response["decision"], "block")
        self.assertIn("decision_capsule_unavailable", result.response["reason"])

    def test_resume_blocks_when_compiler_crashes(self) -> None:
        """v0.2: compiler crash always blocks, resume or not."""
        envelope = self._envelope(prompt="read the file", source="resume")

        with SqliteUnitOfWork(self.config) as uow:
            self._seed_allow_state(uow)
            service = UserPromptSubmitService(uow, self.config, self.paths.raw_events_dir)
            with mock.patch.object(service._compiler, "compile", side_effect=RuntimeError("boom")):
                result = service.handle(envelope)

        self.assertFalse(result.allowed)
        self.assertEqual(result.response["decision"], "block")
        self.assertIn("decision_capsule_unavailable", result.response["reason"])

    def test_capsule_stored_with_audit_fields(self) -> None:
        envelope = self._envelope(prompt="read the file")

        with SqliteUnitOfWork(self.config) as uow:
            self._seed_allow_state(uow)
            UserPromptSubmitService(uow, self.config, self.paths.raw_events_dir).handle(envelope)

        with SqliteUnitOfWork(self.config.db_path) as uow:
            capsules = uow.capsules.list_for_session(self.session_id)

        self.assertEqual(len(capsules), 1)
        self.assertEqual(capsules[0].phase, VerifyPhase.DECISION)
        self.assertTrue(capsules[0].audit_pass)
        self.assertTrue(capsules[0].audit_report["passed"])
        self.assertIn("hard_fail_reasons", capsules[0].audit_report)

    def test_event_logged(self) -> None:
        envelope = self._envelope(prompt="read the file")

        with SqliteUnitOfWork(self.config) as uow:
            self._seed_allow_state(uow)
            UserPromptSubmitService(uow, self.config, self.paths.raw_events_dir).handle(envelope)

        with SqliteUnitOfWork(self.config.db_path) as uow:
            events = uow.events.list_for_session(self.session_id)

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].event_type, "user_prompt_submit.handled")
        self.assertTrue(events[0].payload["allowed"])
        self.assertTrue(Path(events[0].payload["raw_archive_path"]).exists())

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

    def _seed_allow_state(self, uow: SqliteUnitOfWork) -> None:
        self._seed_session(uow)
        obligation = Obligation(
            id="obl-allow",
            session_id=self.session_id,
            source="spec",
            statement="Need supported evidence",
            priority=10,
            status=ObligationStatus.OPEN,
            created_at="2026-03-31T10:00:00Z",
            updated_at="2026-03-31T10:00:00Z",
        )
        evidence = Evidence(
            id="ev-allow",
            session_id=self.session_id,
            kind="command",
            source_tool="pytest",
            path="tests/test_allow.py",
            polarity="positive",
            excerpt="supported evidence",
            created_at="2026-03-31T10:01:00Z",
        )
        assertion = Assertion(
            id="as-allow",
            session_id=self.session_id,
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

    def _seed_block_state(self, uow: SqliteUnitOfWork) -> None:
        self._seed_session(uow)
        obligation = Obligation(
            id="obl-block",
            session_id=self.session_id,
            source="spec",
            statement="Confirmed assertion must be supported",
            priority=10,
            status=ObligationStatus.OPEN,
            created_at="2026-03-31T10:00:00Z",
            updated_at="2026-03-31T10:00:00Z",
        )
        evidence = Evidence(
            id="ev-block",
            session_id=self.session_id,
            kind="command",
            source_tool="pytest",
            path="tests/test_block.py",
            polarity="positive",
            excerpt="confirmed only evidence",
            created_at="2026-03-31T10:01:00Z",
        )
        assertion = Assertion(
            id="as-block",
            session_id=self.session_id,
            obligation_id=obligation.id,
            statement="Unsupported confirmed assertion",
            status=AssertionStatus.CONFIRMED,
            confidence=0.95,
            evidence_ids=[evidence.id],
            created_at="2026-03-31T10:02:00Z",
            updated_at="2026-03-31T10:02:00Z",
        )
        uow.obligations.upsert(obligation)
        uow.evidence.create(evidence)
        uow.assertions.upsert(assertion)

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
                created_at="2026-03-31T09:59:00Z",
                updated_at="2026-03-31T09:59:00Z",
            )
        )


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from egtsr_runtime.config import RuntimeConfig
from egtsr_runtime.db.seed import seed_db
from egtsr_runtime.db.uow import SqliteUnitOfWork
from egtsr_runtime.enums import ObligationStatus, VerifyPhase
from egtsr_runtime.services import VerifyResultsRecorder
from egtsr_runtime.paths import ensure_runtime_dirs

FIXTURE_DIR = Path("tests/fixtures/verify")


class TestVerifyResults(unittest.TestCase):
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

    def test_failing_verify_reopens_obligation(self):
        """fail outcome -> ADDRESSED obligation becomes REOPENED"""
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_fixture(uow, "targeted_fail_reopens_obligation.json")
            result = VerifyResultsRecorder(uow).record(
                session_id="sess-verify",
                phase=VerifyPhase.TARGETED.value,
                outcome="fail",
                affected_obligation_ids=["obl-addressed"],
                excerpt="targeted verify failed",
            )
            uow.commit()

        self.assertEqual(result.reopened_obligation_ids, ["obl-addressed"])
        with SqliteUnitOfWork(self.config.db_path) as uow:
            self.assertEqual(uow.obligations.get("obl-addressed").status, ObligationStatus.REOPENED)

    def test_passing_verify_no_reopen(self):
        """pass outcome -> obligation stays ADDRESSED"""
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_fixture(uow, "targeted_fail_reopens_obligation.json")
            VerifyResultsRecorder(uow).record(
                session_id="sess-verify",
                phase=VerifyPhase.TARGETED.value,
                outcome="pass",
                affected_obligation_ids=["obl-addressed"],
            )
            uow.commit()

        with SqliteUnitOfWork(self.config.db_path) as uow:
            self.assertEqual(uow.obligations.get("obl-addressed").status, ObligationStatus.ADDRESSED)

    def test_verify_result_persisted(self):
        """VerifyResult saved in DB with correct fields"""
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_fixture(uow, "targeted_fail_reopens_obligation.json")
            result = VerifyResultsRecorder(uow).record(
                session_id="sess-verify",
                phase=VerifyPhase.TARGETED.value,
                outcome="fail",
                affected_obligation_ids=["obl-addressed"],
                excerpt="pytest failed",
                metadata={"suite": "targeted"},
            )
            uow.commit()

        with SqliteUnitOfWork(self.config.db_path) as uow:
            stored = uow.verify_results.get(result.verify_result_id)

        self.assertIsNotNone(stored)
        self.assertEqual(stored.phase, VerifyPhase.TARGETED)
        self.assertEqual(stored.outcome, "fail")
        self.assertEqual(stored.affected_obligation_ids, ["obl-addressed"])
        self.assertEqual(stored.excerpt, "pytest failed")
        self.assertEqual(stored.metadata, {"suite": "targeted"})

    def test_verify_ladder_targeted_to_impacted(self):
        """targeted + fail -> next_phase = impacted_surface"""
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_fixture(uow, "targeted_fail_reopens_obligation.json")
            result = VerifyResultsRecorder(uow).record(
                session_id="sess-verify",
                phase=VerifyPhase.TARGETED.value,
                outcome="fail",
                affected_obligation_ids=["obl-addressed"],
            )

        self.assertEqual(result.next_phase, VerifyPhase.IMPACTED_SURFACE.value)

    def test_verify_ladder_impacted_to_broad(self):
        """impacted_surface + fail -> next_phase = broad_smoke"""
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_fixture(uow, "targeted_fail_reopens_obligation.json")
            result = VerifyResultsRecorder(uow).record(
                session_id="sess-verify",
                phase=VerifyPhase.IMPACTED_SURFACE.value,
                outcome="fail",
                affected_obligation_ids=["obl-addressed"],
            )

        self.assertEqual(result.next_phase, VerifyPhase.BROAD_SMOKE.value)

    def test_verify_ladder_broad_no_next(self):
        """broad_smoke -> next_phase = None"""
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_fixture(uow, "targeted_fail_reopens_obligation.json")
            result = VerifyResultsRecorder(uow).record(
                session_id="sess-verify",
                phase=VerifyPhase.BROAD_SMOKE.value,
                outcome="fail",
                affected_obligation_ids=["obl-addressed"],
            )

        self.assertIsNone(result.next_phase)

    def test_verify_ladder_pass_no_next(self):
        """pass outcome at any phase -> next_phase = None"""
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_fixture(uow, "targeted_fail_reopens_obligation.json")
            result = VerifyResultsRecorder(uow).record(
                session_id="sess-verify",
                phase=VerifyPhase.TARGETED.value,
                outcome="pass",
                affected_obligation_ids=["obl-addressed"],
            )

        self.assertIsNone(result.next_phase)

    @staticmethod
    def _seed_fixture(uow: SqliteUnitOfWork, name: str) -> dict:
        payload = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
        seed_db(uow, payload)
        return payload


if __name__ == "__main__":
    unittest.main()

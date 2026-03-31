from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from egtsr_runtime.compiler import DecisionCapsuleCompiler, DecisionCompilerInput
from egtsr_runtime.config import RuntimeConfig
from egtsr_runtime.db.seed import seed_db
from egtsr_runtime.db.uow import SqliteUnitOfWork
from egtsr_runtime.services import AttemptFamilyService
from egtsr_runtime.paths import ensure_runtime_dirs

FIXTURE_DIR = Path("tests/fixtures/verify")


class TestAttemptFamilies(unittest.TestCase):
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

    def test_new_family_created(self):
        """First failure creates new family with fail_count=1"""
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_fixture(uow, "repeated_family_merge.json")
            family = AttemptFamilyService(uow).register_failure(
                session_id="sess-family",
                obligation_id="obl-family",
                touched_files=["src/c.py"],
                outcome="fail",
                excerpt="first new failure",
            )
            uow.commit()

        self.assertEqual(family.fail_count, 1)
        with SqliteUnitOfWork(self.config.db_path) as uow:
            stored = [item for item in uow.attempt_families.list_for_session("sess-family") if item.id == family.id][0]
        self.assertEqual(stored.summary, "first new failure")
        self.assertEqual(stored.touched_scope, ["src/c.py"])

    def test_repeated_failure_merges(self):
        """Same signature -> fail_count increments, summary updates"""
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_fixture(uow, "repeated_family_merge.json")
            family = AttemptFamilyService(uow).register_failure(
                session_id="sess-family",
                obligation_id="obl-family",
                touched_files=["src/b.py", "src/a.py"],
                outcome="fail",
                excerpt="latest merged failure",
            )
            uow.commit()

        self.assertEqual(family.id, "af-existing")
        self.assertEqual(family.fail_count, 3)
        self.assertEqual(family.summary, "latest merged failure")
        with SqliteUnitOfWork(self.config.db_path) as uow:
            stored = uow.attempt_families.list_for_session("sess-family")
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].fail_count, 3)

    def test_different_signature_separate_family(self):
        """Different touched_files -> separate family"""
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_fixture(uow, "repeated_family_merge.json")
            AttemptFamilyService(uow).register_failure(
                session_id="sess-family",
                obligation_id="obl-family",
                touched_files=["src/other.py"],
                outcome="fail",
                excerpt="different path failure",
            )
            uow.commit()

        with SqliteUnitOfWork(self.config.db_path) as uow:
            stored = uow.attempt_families.list_for_session("sess-family")
        self.assertEqual(len(stored), 2)

    def test_family_in_capsule_negative_evidence(self):
        """Recent failed family appears in decision capsule negative_items"""
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_fixture(uow, "repeated_family_merge.json")
            AttemptFamilyService(uow).register_failure(
                session_id="sess-family",
                obligation_id="obl-family",
                touched_files=["src/a.py", "src/b.py"],
                outcome="fail",
                excerpt="api timeout remains",
            )
            capsule = DecisionCapsuleCompiler().compile(
                DecisionCompilerInput(
                    session_id="sess-family",
                    token_budget=500,
                    open_obligations=uow.obligations.list_open("sess-family"),
                    evidence=uow.evidence.list_for_session("sess-family"),
                    assertions=uow.assertions.list_for_session("sess-family"),
                    invalidation_tickets=uow.invalidations.list_for_session("sess-family"),
                    attempt_families=uow.attempt_families.list_for_session("sess-family"),
                )
            )

        block = capsule.obligation_blocks[0]
        self.assertTrue(any("api timeout remains" in item for item in block.negative_items))
        self.assertFalse(any("api timeout remains" in item for item in block.positive_items))

    def test_export_families_json(self):
        """export_families returns list of dicts suitable for JSON/CSV"""
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_fixture(uow, "repeated_family_merge.json")
            exported = AttemptFamilyService(uow).export_families("sess-family")

        self.assertEqual(len(exported), 1)
        self.assertEqual(exported[0]["id"], "af-existing")
        self.assertEqual(exported[0]["signature"], "14abcfb1574acb2a")
        self.assertIsInstance(json.dumps(exported), str)

    def test_deterministic_signature(self):
        """Same inputs produce same signature"""
        signature_a = AttemptFamilyService.compute_signature("obl-family", ["src/b.py", "src/a.py"])
        signature_b = AttemptFamilyService.compute_signature("obl-family", ["src/a.py", "src/b.py"])

        self.assertEqual(signature_a, signature_b)
        self.assertEqual(signature_a, "14abcfb1574acb2a")

    @staticmethod
    def _seed_fixture(uow: SqliteUnitOfWork, name: str) -> dict:
        payload = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
        seed_db(uow, payload)
        return payload


if __name__ == "__main__":
    unittest.main()

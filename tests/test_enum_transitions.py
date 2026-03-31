import tempfile
import unittest

from egtsr_runtime.config import RuntimeConfig
from egtsr_runtime.db.uow import SqliteUnitOfWork
from egtsr_runtime.enums import AssertionStatus, InvalidationStatus, ObligationStatus, VerifyPhase
from egtsr_runtime.models import Assertion, Capsule, InvalidationTicket, Obligation, Session, VerifyResult
from egtsr_runtime.paths import ensure_runtime_dirs


class EnumTransitionTests(unittest.TestCase):
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

    def test_enum_values_are_stored_as_strings_and_round_trip(self) -> None:
        config = self._config()
        session = Session(
            id="sess-enum",
            repo_root=config.repo_root,
            branch="main",
            head_hash=None,
            status="active",
            created_at="2026-03-31T13:00:00Z",
            updated_at="2026-03-31T13:00:00Z",
        )
        obligation = Obligation(
            id="obl-enum",
            session_id=session.id,
            source="spec",
            statement="enum storage",
            status=ObligationStatus.REOPENED,
            created_at="2026-03-31T13:01:00Z",
            updated_at="2026-03-31T13:01:00Z",
        )
        assertion = Assertion(
            id="as-enum",
            session_id=session.id,
            obligation_id=obligation.id,
            statement="assertion enum",
            status=AssertionStatus.STALE,
            created_at="2026-03-31T13:02:00Z",
            updated_at="2026-03-31T13:02:00Z",
        )
        invalidation = InvalidationTicket(
            id="inv-enum",
            session_id=session.id,
            subject_type="assertion",
            subject_id=assertion.id,
            trigger_kind="verify",
            status=InvalidationStatus.REVALIDATED,
            created_at="2026-03-31T13:03:00Z",
            updated_at="2026-03-31T13:03:00Z",
        )
        verify_result = VerifyResult(
            id="vr-enum",
            session_id=session.id,
            phase=VerifyPhase.IMPACTED_SURFACE,
            outcome="passed",
            created_at="2026-03-31T13:04:00Z",
        )
        capsule = Capsule(
            id="cap-enum",
            session_id=session.id,
            phase=VerifyPhase.BROAD_SMOKE,
            frontier_hash="frontier-e",
            content="enum capsule",
            token_count=10,
            audit_pass=True,
            created_at="2026-03-31T13:05:00Z",
        )

        with SqliteUnitOfWork(config) as uow:
            uow.sessions.create(session)
            uow.obligations.upsert(obligation)
            uow.assertions.upsert(assertion)
            uow.invalidations.upsert(invalidation)
            uow.verify_results.create(verify_result)
            uow.capsules.create(capsule)
            row = uow.conn.execute(
                """
                SELECT
                    (SELECT status FROM obligations WHERE id = ?) AS obligation_status,
                    (SELECT status FROM assertions WHERE id = ?) AS assertion_status,
                    (SELECT status FROM invalidation_tickets WHERE id = ?) AS invalidation_status,
                    (SELECT phase FROM verify_results WHERE id = ?) AS verify_phase,
                    (SELECT phase FROM capsules WHERE id = ?) AS capsule_phase
                """,
                (obligation.id, assertion.id, invalidation.id, verify_result.id, capsule.id),
            ).fetchone()
            uow.commit()

        self.assertEqual(row["obligation_status"], ObligationStatus.REOPENED.value)
        self.assertEqual(row["assertion_status"], AssertionStatus.STALE.value)
        self.assertEqual(row["invalidation_status"], InvalidationStatus.REVALIDATED.value)
        self.assertEqual(row["verify_phase"], VerifyPhase.IMPACTED_SURFACE.value)
        self.assertEqual(row["capsule_phase"], VerifyPhase.BROAD_SMOKE.value)
        self.assertEqual(ObligationStatus.REOPENED, "reopened")
        self.assertEqual(AssertionStatus.STALE, "stale")

        with SqliteUnitOfWork(config.db_path) as uow:
            self.assertEqual(uow.obligations.get(obligation.id).status, ObligationStatus.REOPENED)
            self.assertEqual(uow.assertions.get(assertion.id).status, AssertionStatus.STALE)
            self.assertEqual(uow.invalidations.get(invalidation.id).status, InvalidationStatus.REVALIDATED)
            self.assertEqual(uow.verify_results.get(verify_result.id).phase, VerifyPhase.IMPACTED_SURFACE)
            self.assertEqual(uow.capsules.get(capsule.id).phase, VerifyPhase.BROAD_SMOKE)


if __name__ == "__main__":
    unittest.main()

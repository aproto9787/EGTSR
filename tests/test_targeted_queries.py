"""Tests for Step 04 — targeted query API on canonical and projection repos."""
import tempfile
import unittest
from datetime import datetime, timezone

from egtsr_runtime.config import RuntimeConfig
from egtsr_runtime.db.uow import SqliteUnitOfWork
from egtsr_runtime.enums import (
    AssertionStatus,
    InvalidationStatus,
    ObligationStatus,
)
from egtsr_runtime.models import (
    Assertion,
    AttemptFamily,
    Evidence,
    InvalidationTicket,
    Obligation,
    RepoState,
    Session,
)
from egtsr_runtime.paths import ensure_runtime_dirs
from egtsr_runtime.services.projections import (
    on_assertion_upsert,
    on_attempt_family_upsert,
    on_evidence_create,
    on_obligation_upsert,
    sync_session_frontier,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _BaseTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        paths = ensure_runtime_dirs(self.tmp_dir.name)
        self.config = RuntimeConfig(
            repo_root=paths.repo_root,
            egtsr_dir=paths.egtsr_dir,
            db_path=paths.db_path,
        )

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _seed_session(self, uow: SqliteUnitOfWork, session_id: str = "sess-1") -> Session:
        session = Session(
            id=session_id,
            repo_root=self.config.repo_root,
            branch="main",
            head_hash="abc123",
            status="active",
            created_at=_now(),
            updated_at=_now(),
        )
        uow.sessions.create(session)
        return session


class TestObligationTargetedQueries(_BaseTestCase):
    def test_list_open_ids(self) -> None:
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            now = _now()
            for i, status in enumerate(
                [ObligationStatus.OPEN, ObligationStatus.VERIFIED, ObligationStatus.REOPENED]
            ):
                uow.obligations.upsert(
                    Obligation(
                        id=f"obl-{i}",
                        session_id="sess-1",
                        source="test",
                        statement=f"obl {i}",
                        status=status,
                        created_at=now,
                        updated_at=now,
                    )
                )
            uow.commit()

            ids = uow.obligations.list_open_ids("sess-1")
            self.assertIn("obl-0", ids)
            self.assertIn("obl-2", ids)
            self.assertNotIn("obl-1", ids)

    def test_list_by_ids_ordered(self) -> None:
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            now = _now()
            for i in range(5):
                uow.obligations.upsert(
                    Obligation(
                        id=f"obl-{i}",
                        session_id="sess-1",
                        source="test",
                        statement=f"obl {i}",
                        created_at=now,
                        updated_at=now,
                    )
                )
            uow.commit()

            result = uow.obligations.list_by_ids_ordered("sess-1", ["obl-1", "obl-3"])
            self.assertEqual([o.id for o in result], ["obl-1", "obl-3"])

    def test_list_by_ids_ordered_empty(self) -> None:
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            uow.commit()
            result = uow.obligations.list_by_ids_ordered("sess-1", [])
            self.assertEqual(result, [])

    def test_bulk_mark_reopened(self) -> None:
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            now = _now()
            for i in range(3):
                uow.obligations.upsert(
                    Obligation(
                        id=f"obl-{i}",
                        session_id="sess-1",
                        source="test",
                        statement=f"obl {i}",
                        status=ObligationStatus.VERIFIED,
                        created_at=now,
                        updated_at=now,
                    )
                )
            uow.commit()

            uow.obligations.bulk_mark_reopened(["obl-0", "obl-2"], _now())
            uow.commit()

            self.assertEqual(uow.obligations.get("obl-0").status, ObligationStatus.REOPENED)
            self.assertEqual(uow.obligations.get("obl-1").status, ObligationStatus.VERIFIED)
            self.assertEqual(uow.obligations.get("obl-2").status, ObligationStatus.REOPENED)


class TestAssertionTargetedQueries(_BaseTestCase):
    def test_list_by_ids(self) -> None:
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            now = _now()
            for i in range(3):
                uow.assertions.upsert(
                    Assertion(
                        id=f"as-{i}",
                        session_id="sess-1",
                        obligation_id=None,
                        statement=f"as {i}",
                        created_at=now,
                        updated_at=now,
                    )
                )
            uow.commit()

            result = uow.assertions.list_by_ids(["as-0", "as-2"])
            self.assertEqual({a.id for a in result}, {"as-0", "as-2"})

    def test_list_active_by_obligation_ids(self) -> None:
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            now = _now()
            uow.obligations.upsert(
                Obligation(id="obl-1", session_id="sess-1", source="test", statement="obl", created_at=now, updated_at=now)
            )
            uow.assertions.upsert(
                Assertion(id="as-active", session_id="sess-1", obligation_id="obl-1", statement="active",
                          status=AssertionStatus.SUPPORTED, created_at=now, updated_at=now)
            )
            uow.assertions.upsert(
                Assertion(id="as-stale", session_id="sess-1", obligation_id="obl-1", statement="stale",
                          status=AssertionStatus.STALE, created_at=now, updated_at=now)
            )
            uow.commit()

            result = uow.assertions.list_active_by_obligation_ids(["obl-1"])
            self.assertEqual([a.id for a in result], ["as-active"])

    def test_bulk_mark_stale(self) -> None:
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            now = _now()
            for i in range(3):
                uow.assertions.upsert(
                    Assertion(id=f"as-{i}", session_id="sess-1", obligation_id=None, statement=f"as {i}",
                              status=AssertionStatus.SUPPORTED, created_at=now, updated_at=now)
                )
            uow.commit()

            uow.assertions.bulk_mark_stale(["as-0", "as-2"], _now())
            uow.commit()

            self.assertEqual(uow.assertions.get("as-0").status, AssertionStatus.STALE)
            self.assertEqual(uow.assertions.get("as-1").status, AssertionStatus.SUPPORTED)
            self.assertEqual(uow.assertions.get("as-2").status, AssertionStatus.STALE)

    def test_list_obligation_ids_for_assertions(self) -> None:
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            now = _now()
            uow.obligations.upsert(
                Obligation(id="obl-1", session_id="sess-1", source="test", statement="obl1", created_at=now, updated_at=now)
            )
            uow.obligations.upsert(
                Obligation(id="obl-2", session_id="sess-1", source="test", statement="obl2", created_at=now, updated_at=now)
            )
            uow.assertions.upsert(
                Assertion(id="as-a", session_id="sess-1", obligation_id="obl-1", statement="a", created_at=now, updated_at=now)
            )
            uow.assertions.upsert(
                Assertion(id="as-b", session_id="sess-1", obligation_id="obl-2", statement="b", created_at=now, updated_at=now)
            )
            uow.assertions.upsert(
                Assertion(id="as-c", session_id="sess-1", obligation_id=None, statement="c", created_at=now, updated_at=now)
            )
            uow.commit()

            result = uow.assertions.list_obligation_ids_for_assertions(["as-a", "as-b", "as-c"])
            self.assertEqual(set(result), {"obl-1", "obl-2"})


class TestEvidenceTargetedQueries(_BaseTestCase):
    def test_list_by_ids(self) -> None:
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            now = _now()
            for i in range(3):
                uow.evidence.create(
                    Evidence(id=f"ev-{i}", session_id="sess-1", kind="cmd", source_tool="test", created_at=now)
                )
            uow.commit()

            result = uow.evidence.list_by_ids(["ev-0", "ev-2"])
            self.assertEqual({e.id for e in result}, {"ev-0", "ev-2"})

    def test_bulk_create(self) -> None:
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            now = _now()
            items = [
                Evidence(id=f"ev-{i}", session_id="sess-1", kind="cmd", source_tool="test", created_at=now)
                for i in range(5)
            ]
            uow.evidence.bulk_create(items)
            uow.commit()

            for i in range(5):
                self.assertIsNotNone(uow.evidence.get(f"ev-{i}"))


class TestInvalidationTargetedQueries(_BaseTestCase):
    def test_list_live_for_assertions(self) -> None:
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            now = _now()
            uow.invalidations.upsert(
                InvalidationTicket(
                    id="inv-1", session_id="sess-1", subject_type="assertion", subject_id="as-1",
                    trigger_kind="file_touch", status=InvalidationStatus.LIVE, created_at=now, updated_at=now,
                )
            )
            uow.invalidations.upsert(
                InvalidationTicket(
                    id="inv-2", session_id="sess-1", subject_type="assertion", subject_id="as-1",
                    trigger_kind="file_touch", status=InvalidationStatus.CLOSED, created_at=now, updated_at=now,
                )
            )
            uow.invalidations.upsert(
                InvalidationTicket(
                    id="inv-3", session_id="sess-1", subject_type="obligation", subject_id="obl-1",
                    trigger_kind="file_touch", status=InvalidationStatus.LIVE, created_at=now, updated_at=now,
                )
            )
            uow.commit()

            result = uow.invalidations.list_live_for_assertions(["as-1"])
            self.assertEqual([t.id for t in result], ["inv-1"])

    def test_list_live_for_obligations(self) -> None:
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            now = _now()
            uow.invalidations.upsert(
                InvalidationTicket(
                    id="inv-1", session_id="sess-1", subject_type="obligation", subject_id="obl-1",
                    trigger_kind="file_touch", status=InvalidationStatus.LIVE, created_at=now, updated_at=now,
                )
            )
            uow.commit()

            result = uow.invalidations.list_live_for_obligations(["obl-1"])
            self.assertEqual([t.id for t in result], ["inv-1"])

    def test_bulk_upsert(self) -> None:
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            now = _now()
            tickets = [
                InvalidationTicket(
                    id=f"inv-{i}", session_id="sess-1", subject_type="assertion", subject_id=f"as-{i}",
                    trigger_kind="file_touch", status=InvalidationStatus.LIVE, created_at=now, updated_at=now,
                )
                for i in range(3)
            ]
            uow.invalidations.bulk_upsert(tickets)
            uow.commit()

            for i in range(3):
                self.assertIsNotNone(uow.invalidations.get(f"inv-{i}"))


class TestAttemptFamilyTargetedQueries(_BaseTestCase):
    def test_get_by_signature(self) -> None:
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            now = _now()
            uow.obligations.upsert(
                Obligation(id="obl-1", session_id="sess-1", source="test", statement="obl", created_at=now, updated_at=now)
            )
            uow.attempt_families.upsert(
                AttemptFamily(
                    id="af-1", session_id="sess-1", obligation_id="obl-1",
                    signature="sig-abc", touched_scope=["a.py"],
                    fail_count=1, last_outcome="fail", created_at=now, updated_at=now,
                )
            )
            uow.commit()

            result = uow.attempt_families.get_by_signature("sess-1", "sig-abc")
            self.assertIsNotNone(result)
            self.assertEqual(result.id, "af-1")

            result_miss = uow.attempt_families.get_by_signature("sess-1", "sig-xyz")
            self.assertIsNone(result_miss)

            result_wrong_session = uow.attempt_families.get_by_signature("sess-2", "sig-abc")
            self.assertIsNone(result_wrong_session)

    def test_list_recent_failures_by_obligation_ids(self) -> None:
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            now = _now()
            uow.obligations.upsert(
                Obligation(id="obl-1", session_id="sess-1", source="test", statement="obl", created_at=now, updated_at=now)
            )
            for i in range(4):
                uow.attempt_families.upsert(
                    AttemptFamily(
                        id=f"af-{i}", session_id="sess-1", obligation_id="obl-1",
                        signature=f"sig-{i}", touched_scope=[f"f{i}.py"],
                        fail_count=1, last_outcome="fail",
                        created_at=now, updated_at=now,
                    )
                )
            # One success should be excluded
            uow.attempt_families.upsert(
                AttemptFamily(
                    id="af-ok", session_id="sess-1", obligation_id="obl-1",
                    signature="sig-ok", touched_scope=["ok.py"],
                    fail_count=0, last_outcome="pass",
                    created_at=now, updated_at=now,
                )
            )
            uow.commit()

            result = uow.attempt_families.list_recent_failures_by_obligation_ids(["obl-1"], limit_per_obligation=2)
            self.assertEqual(len(result), 2)
            for f in result:
                self.assertEqual(f.last_outcome, "fail")


class TestRepoStateTargetedQueries(_BaseTestCase):
    def test_mark_dirty_and_clear(self) -> None:
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            now = _now()
            uow.repo_state.upsert(
                RepoState(session_id="sess-1", head_hash="abc", dirty=False, changed_files=[], last_scan_at=now)
            )
            uow.commit()

            uow.repo_state.mark_dirty("sess-1", ["x.py", "y.py"], _now())
            uow.commit()

            state = uow.repo_state.get("sess-1")
            self.assertTrue(state.dirty)
            self.assertEqual(state.changed_files, ["x.py", "y.py"])

            uow.repo_state.clear_dirty("sess-1", _now())
            uow.commit()

            state = uow.repo_state.get("sess-1")
            self.assertFalse(state.dirty)
            self.assertEqual(state.changed_files, [])


class TestProjectionRepos(_BaseTestCase):
    def _seed_with_projections(self, uow: SqliteUnitOfWork) -> None:
        """Seed canonical data and trigger projection sync."""
        self._seed_session(uow)
        now = _now()

        obl = Obligation(
            id="obl-1", session_id="sess-1", source="test", statement="obl",
            priority=1, status=ObligationStatus.OPEN, created_at=now, updated_at=now,
        )
        uow.obligations.upsert(obl)
        on_obligation_upsert(uow._require_connection(), obl)

        ev = Evidence(
            id="ev-1", session_id="sess-1", kind="cmd", source_tool="test",
            path="src/main.py", scope_ref="src/main.py", created_at=now,
        )
        uow.evidence.create(ev)
        on_evidence_create(uow._require_connection(), ev)

        assertion = Assertion(
            id="as-1", session_id="sess-1", obligation_id="obl-1",
            statement="assert", scope_kind="file", scope_ref="src/main.py",
            status=AssertionStatus.SUPPORTED, evidence_ids=["ev-1"],
            created_at=now, updated_at=now,
        )
        uow.assertions.upsert(assertion)
        on_assertion_upsert(uow._require_connection(), assertion)

        family = AttemptFamily(
            id="af-1", session_id="sess-1", obligation_id="obl-1",
            signature="sig-1", touched_scope=["src/main.py"],
            fail_count=1, last_outcome="fail", created_at=now, updated_at=now,
        )
        uow.attempt_families.upsert(family)
        on_attempt_family_upsert(uow._require_connection(), family)

        sync_session_frontier(uow._require_connection(), "sess-1")
        uow.commit()

    def test_path_subject_index_lookup(self) -> None:
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_with_projections(uow)

            # assertion subjects for path
            subjects = uow.path_subject_index.list_subject_ids_for_paths(
                "sess-1", ["src/main.py"], "assertion"
            )
            self.assertIn("as-1", subjects)

            # evidence subjects for path
            subjects = uow.path_subject_index.list_subject_ids_for_paths(
                "sess-1", ["src/main.py"], "evidence"
            )
            self.assertIn("ev-1", subjects)

            # attempt_family subjects for path
            subjects = uow.path_subject_index.list_subject_ids_for_paths(
                "sess-1", ["src/main.py"], "attempt_family"
            )
            self.assertIn("af-1", subjects)

    def test_path_subject_index_all_types(self) -> None:
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_with_projections(uow)

            rows = uow.path_subject_index.list_subjects_for_paths("sess-1", ["src/main.py"])
            types = {r.subject_type for r in rows}
            self.assertTrue(types.issuperset({"assertion", "evidence", "attempt_family"}))

    def test_path_subject_index_reverse(self) -> None:
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_with_projections(uow)

            paths = uow.path_subject_index.list_paths_for_subject("sess-1", "assertion", "as-1")
            self.assertIn("src/main.py", paths)

    def test_assertion_evidence_links(self) -> None:
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_with_projections(uow)

            eids = uow.assertion_evidence_links.list_evidence_ids_for_assertion("as-1")
            self.assertEqual(eids, ["ev-1"])

            aids = uow.assertion_evidence_links.list_assertion_ids_for_evidence("ev-1")
            self.assertEqual(aids, ["as-1"])

    def test_assertion_evidence_links_batch(self) -> None:
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_with_projections(uow)

            result = uow.assertion_evidence_links.list_evidence_ids_for_assertions(["as-1"])
            self.assertEqual(result, {"as-1": ["ev-1"]})

    def test_obligation_frontier_dirty(self) -> None:
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_with_projections(uow)

            dirty = uow.obligation_frontier.list_dirty("sess-1")
            self.assertEqual(len(dirty), 1)
            self.assertEqual(dirty[0].obligation_id, "obl-1")
            self.assertTrue(dirty[0].dirty)

    def test_obligation_frontier_mark_clean(self) -> None:
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_with_projections(uow)

            uow.obligation_frontier.mark_clean("obl-1", _now())
            uow.commit()

            dirty = uow.obligation_frontier.list_dirty("sess-1")
            self.assertEqual(len(dirty), 0)

            row = uow.obligation_frontier.get("obl-1")
            self.assertFalse(row.dirty)

    def test_obligation_frontier_open(self) -> None:
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_with_projections(uow)

            open_ids = uow.obligation_frontier.list_open_ids("sess-1")
            self.assertIn("obl-1", open_ids)

    def test_session_frontier(self) -> None:
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_with_projections(uow)

            sf = uow.session_frontier.get("sess-1")
            self.assertIsNotNone(sf)
            self.assertGreaterEqual(sf.dirty_obligation_count, 0)

            version = uow.session_frontier.get_frontier_version("sess-1")
            self.assertIsNotNone(version)

    def test_session_frontier_update_compiled(self) -> None:
        with SqliteUnitOfWork(self.config) as uow:
            self._seed_with_projections(uow)
            now = _now()
            uow.session_frontier.update_last_compiled("sess-1", "cap-1", "hash-1", now)
            uow.commit()

            sf = uow.session_frontier.get("sess-1")
            self.assertEqual(sf.last_compiled_capsule_id, "cap-1")
            self.assertEqual(sf.last_frontier_hash, "hash-1")


class TestAttemptFamilyServiceIndexedLookup(_BaseTestCase):
    def test_register_failure_uses_indexed_lookup(self) -> None:
        """Verify AttemptFamilyService.register_failure uses get_by_signature."""
        from egtsr_runtime.services.attempt_families import AttemptFamilyService

        with SqliteUnitOfWork(self.config) as uow:
            self._seed_session(uow)
            now = _now()
            uow.obligations.upsert(
                Obligation(id="obl-1", session_id="sess-1", source="test", statement="obl", created_at=now, updated_at=now)
            )
            svc = AttemptFamilyService(uow)

            # First failure
            f1 = svc.register_failure("sess-1", "obl-1", ["a.py"], "fail", "first")
            uow.commit()
            self.assertEqual(f1.fail_count, 1)

            # Same signature → should merge
            f2 = svc.register_failure("sess-1", "obl-1", ["a.py"], "fail", "second")
            uow.commit()
            self.assertEqual(f2.id, f1.id)
            self.assertEqual(f2.fail_count, 2)


if __name__ == "__main__":
    unittest.main()

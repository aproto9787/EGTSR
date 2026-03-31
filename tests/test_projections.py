"""Tests for Step 03: Projection Schema + Backfill.

Covers:
- Path normalization helper
- Projection maintenance (dual-write sync)
- Backfill idempotency
- Corrupted projection recovery
- Canonical/projection consistency
"""
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone

from egtsr_runtime.db.connection import get_connection
from egtsr_runtime.db.migrations import run_migrations
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
)
from egtsr_runtime.paths import ensure_runtime_dirs
from egtsr_runtime.repositories.assertions import SqliteAssertionRepository
from egtsr_runtime.repositories.attempt_families import SqliteAttemptFamilyRepository
from egtsr_runtime.repositories.evidence import SqliteEvidenceRepository
from egtsr_runtime.repositories.invalidations import SqliteInvalidationRepository
from egtsr_runtime.repositories.obligations import SqliteObligationRepository
from egtsr_runtime.repositories.sessions import SqliteSessionRepository
from egtsr_runtime.services.projection_backfill import (
    rebuild_projections,
    rebuild_session_projections,
)
from egtsr_runtime.services.projections import (
    on_assertion_upsert,
    on_attempt_family_upsert,
    on_evidence_create,
    on_invalidation_upsert,
    on_obligation_upsert,
    on_repo_state_change,
    sync_session_frontier,
)
from egtsr_runtime.utils.paths import normalize_path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_conn(tmp_dir: str) -> sqlite3.Connection:
    paths = ensure_runtime_dirs(tmp_dir)
    conn = get_connection(paths.db_path)
    run_migrations(conn)
    return conn


def _insert_session(conn: sqlite3.Connection, session_id: str = "sess-1") -> None:
    conn.execute(
        """INSERT OR IGNORE INTO sessions
           (id, repo_root, branch, head_hash, status, created_at, updated_at)
           VALUES (?, '/repo', 'main', 'abc123', 'active', ?, ?)""",
        (session_id, _now(), _now()),
    )


def _make_obligation(
    session_id: str = "sess-1",
    obligation_id: str = "obl-1",
    priority: int = 50,
    status: ObligationStatus = ObligationStatus.OPEN,
) -> Obligation:
    now = _now()
    return Obligation(
        id=obligation_id,
        session_id=session_id,
        source="test",
        statement="test obligation",
        priority=priority,
        status=status,
        created_at=now,
        updated_at=now,
    )


def _make_assertion(
    session_id: str = "sess-1",
    assertion_id: str = "asr-1",
    obligation_id: str | None = "obl-1",
    scope_ref: str | None = "src/main.py",
    status: AssertionStatus = AssertionStatus.SUPPORTED,
    evidence_ids: list[str] | None = None,
) -> Assertion:
    now = _now()
    return Assertion(
        id=assertion_id,
        session_id=session_id,
        obligation_id=obligation_id,
        statement="test assertion",
        scope_kind="file",
        scope_ref=scope_ref,
        status=status,
        confidence=0.8,
        evidence_ids=evidence_ids or [],
        created_at=now,
        updated_at=now,
    )


def _make_evidence(
    session_id: str = "sess-1",
    evidence_id: str = "ev-1",
    path: str | None = "src/main.py",
    scope_ref: str | None = "src/module.py",
) -> Evidence:
    now = _now()
    return Evidence(
        id=evidence_id,
        session_id=session_id,
        kind="file_content",
        source_tool="Read",
        path=path,
        scope_kind="file",
        scope_ref=scope_ref,
        polarity="positive",
        created_at=now,
    )


def _make_family(
    session_id: str = "sess-1",
    family_id: str = "fam-1",
    obligation_id: str | None = "obl-1",
    touched_scope: list | None = None,
    last_outcome: str = "pass",
) -> AttemptFamily:
    now = _now()
    return AttemptFamily(
        id=family_id,
        session_id=session_id,
        obligation_id=obligation_id,
        signature="sig-1",
        touched_scope=touched_scope or ["src/main.py"],
        fail_count=0 if last_outcome == "pass" else 1,
        last_outcome=last_outcome,
        created_at=now,
        updated_at=now,
    )


# ===========================================================================
# Path normalization
# ===========================================================================

class TestNormalizePath(unittest.TestCase):
    def test_none_returns_empty(self) -> None:
        self.assertEqual(normalize_path(None), "")

    def test_empty_returns_empty(self) -> None:
        self.assertEqual(normalize_path(""), "")

    def test_whitespace_only_returns_empty(self) -> None:
        self.assertEqual(normalize_path("   "), "")

    def test_strips_whitespace(self) -> None:
        self.assertEqual(normalize_path("  src/main.py  "), "src/main.py")

    def test_normpath_removes_dot_segments(self) -> None:
        self.assertEqual(normalize_path("src/./main.py"), "src/main.py")

    def test_normpath_resolves_dotdot(self) -> None:
        self.assertEqual(normalize_path("src/sub/../main.py"), "src/main.py")

    def test_trailing_slash_removed(self) -> None:
        self.assertEqual(normalize_path("src/dir/"), "src/dir")

    def test_double_slash_normalized(self) -> None:
        self.assertEqual(normalize_path("src//main.py"), "src/main.py")

    def test_repo_root_absolute_to_relative(self) -> None:
        self.assertEqual(
            normalize_path("/home/user/repo/src/main.py", repo_root="/home/user/repo"),
            "src/main.py",
        )

    def test_repo_root_absolute_exact_root(self) -> None:
        self.assertEqual(
            normalize_path("/home/user/repo", repo_root="/home/user/repo"),
            ".",
        )

    def test_repo_root_outside_stays_absolute(self) -> None:
        self.assertEqual(
            normalize_path("/other/path/file.py", repo_root="/home/user/repo"),
            "/other/path/file.py",
        )

    def test_repo_root_relative_path_unchanged(self) -> None:
        self.assertEqual(
            normalize_path("src/main.py", repo_root="/home/user/repo"),
            "src/main.py",
        )

    def test_repo_root_none_no_effect(self) -> None:
        self.assertEqual(
            normalize_path("/home/user/repo/src/main.py", repo_root=None),
            "/home/user/repo/src/main.py",
        )

    def test_repo_root_with_trailing_slash(self) -> None:
        self.assertEqual(
            normalize_path("/home/user/repo/src/main.py", repo_root="/home/user/repo/"),
            "src/main.py",
        )


# ===========================================================================
# Projection maintenance (dual-write sync)
# ===========================================================================

class TestAssertionEvidenceLinks(unittest.TestCase):
    def test_sync_creates_links(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = _make_conn(tmp)
            _insert_session(conn)
            obl = _make_obligation()
            SqliteObligationRepository(conn).upsert(obl)
            on_obligation_upsert(conn, obl)
            # Evidence records must exist for FK
            for eid in ("ev-1", "ev-2"):
                ev = _make_evidence(evidence_id=eid, path=f"src/{eid}.py")
                SqliteEvidenceRepository(conn).create(ev)
            assertion = _make_assertion(evidence_ids=["ev-1", "ev-2"])
            SqliteAssertionRepository(conn).upsert(assertion)
            on_assertion_upsert(conn, assertion)

            rows = conn.execute(
                "SELECT * FROM assertion_evidence_links WHERE assertion_id = ?",
                (assertion.id,),
            ).fetchall()
            self.assertEqual(len(rows), 2)
            evidence_ids = {r["evidence_id"] for r in rows}
            self.assertEqual(evidence_ids, {"ev-1", "ev-2"})
            conn.close()

    def test_sync_replaces_on_update(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = _make_conn(tmp)
            _insert_session(conn)
            obl = _make_obligation()
            SqliteObligationRepository(conn).upsert(obl)
            on_obligation_upsert(conn, obl)
            for eid in ("ev-1", "ev-2", "ev-3"):
                ev = _make_evidence(evidence_id=eid, path=f"src/{eid}.py")
                SqliteEvidenceRepository(conn).create(ev)
            assertion = _make_assertion(evidence_ids=["ev-1", "ev-2"])
            SqliteAssertionRepository(conn).upsert(assertion)
            on_assertion_upsert(conn, assertion)

            # Update with different evidence
            assertion.evidence_ids = ["ev-3"]
            SqliteAssertionRepository(conn).upsert(assertion)
            on_assertion_upsert(conn, assertion)

            rows = conn.execute(
                "SELECT evidence_id FROM assertion_evidence_links WHERE assertion_id = ?",
                (assertion.id,),
            ).fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["evidence_id"], "ev-3")
            conn.close()


class TestPathSubjectIndex(unittest.TestCase):
    def test_assertion_scope_ref_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = _make_conn(tmp)
            _insert_session(conn)
            obl = _make_obligation()
            SqliteObligationRepository(conn).upsert(obl)
            on_obligation_upsert(conn, obl)
            assertion = _make_assertion(scope_ref="src/main.py")
            SqliteAssertionRepository(conn).upsert(assertion)
            on_assertion_upsert(conn, assertion)

            rows = conn.execute(
                "SELECT * FROM path_subject_index WHERE subject_type = 'assertion' AND subject_id = ?",
                (assertion.id,),
            ).fetchall()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["normalized_path"], "src/main.py")
            self.assertEqual(rows[0]["role"], "assertion.scope_ref")
            conn.close()

    def test_evidence_path_and_scope_ref_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = _make_conn(tmp)
            _insert_session(conn)
            evidence = _make_evidence(path="src/main.py", scope_ref="src/module.py")
            SqliteEvidenceRepository(conn).create(evidence)
            on_evidence_create(conn, evidence)

            rows = conn.execute(
                "SELECT * FROM path_subject_index WHERE subject_type = 'evidence' AND subject_id = ?",
                (evidence.id,),
            ).fetchall()
            self.assertEqual(len(rows), 2)
            paths = {r["normalized_path"] for r in rows}
            self.assertEqual(paths, {"src/main.py", "src/module.py"})
            conn.close()

    def test_attempt_family_touched_scope_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = _make_conn(tmp)
            _insert_session(conn)
            obl = _make_obligation()
            SqliteObligationRepository(conn).upsert(obl)
            on_obligation_upsert(conn, obl)

            family = _make_family(touched_scope=["src/a.py", "src/b.py"])
            SqliteAttemptFamilyRepository(conn).upsert(family)
            on_attempt_family_upsert(conn, family)

            rows = conn.execute(
                "SELECT * FROM path_subject_index WHERE subject_type = 'attempt_family' AND subject_id = ?",
                (family.id,),
            ).fetchall()
            self.assertEqual(len(rows), 2)
            conn.close()

    def test_none_scope_ref_not_indexed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = _make_conn(tmp)
            _insert_session(conn)
            obl = _make_obligation()
            SqliteObligationRepository(conn).upsert(obl)
            on_obligation_upsert(conn, obl)
            assertion = _make_assertion(scope_ref=None)
            SqliteAssertionRepository(conn).upsert(assertion)
            on_assertion_upsert(conn, assertion)

            count = conn.execute(
                "SELECT COUNT(*) FROM path_subject_index WHERE subject_type = 'assertion' AND subject_id = ?",
                (assertion.id,),
            ).fetchone()[0]
            self.assertEqual(count, 0)
            conn.close()


class TestObligationFrontier(unittest.TestCase):
    def test_obligation_upsert_creates_frontier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = _make_conn(tmp)
            _insert_session(conn)
            obl = _make_obligation()
            SqliteObligationRepository(conn).upsert(obl)
            on_obligation_upsert(conn, obl)

            row = conn.execute(
                "SELECT * FROM obligation_frontier WHERE obligation_id = ?",
                (obl.id,),
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["dirty"], 1)
            self.assertEqual(row["obligation_status"], "open")
            self.assertEqual(row["priority"], 50)
            conn.close()

    def test_assertion_upsert_dirties_obligation_frontier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = _make_conn(tmp)
            _insert_session(conn)
            obl = _make_obligation()
            SqliteObligationRepository(conn).upsert(obl)
            on_obligation_upsert(conn, obl)

            # Clear dirty
            conn.execute(
                "UPDATE obligation_frontier SET dirty = 0, dirty_reasons_json = '[]' WHERE obligation_id = ?",
                (obl.id,),
            )

            assertion = _make_assertion(obligation_id=obl.id, status=AssertionStatus.SUPPORTED)
            SqliteAssertionRepository(conn).upsert(assertion)
            on_assertion_upsert(conn, assertion)

            row = conn.execute(
                "SELECT * FROM obligation_frontier WHERE obligation_id = ?",
                (obl.id,),
            ).fetchone()
            self.assertEqual(row["dirty"], 1)
            self.assertEqual(row["supported_assertion_count"], 1)
            conn.close()

    def test_invalidation_dirties_obligation_frontier(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = _make_conn(tmp)
            _insert_session(conn)
            obl = _make_obligation()
            SqliteObligationRepository(conn).upsert(obl)
            on_obligation_upsert(conn, obl)

            conn.execute(
                "UPDATE obligation_frontier SET dirty = 0, dirty_reasons_json = '[]' WHERE obligation_id = ?",
                (obl.id,),
            )

            ticket = InvalidationTicket(
                id="inv-1",
                session_id="sess-1",
                subject_type="obligation",
                subject_id=obl.id,
                trigger_kind="file_touch",
                trigger_ref="src/main.py",
                status=InvalidationStatus.LIVE,
                created_at=_now(),
                updated_at=_now(),
            )
            SqliteInvalidationRepository(conn).upsert(ticket)
            on_invalidation_upsert(conn, ticket)

            row = conn.execute(
                "SELECT * FROM obligation_frontier WHERE obligation_id = ?",
                (obl.id,),
            ).fetchone()
            self.assertEqual(row["dirty"], 1)
            conn.close()

    def test_assertion_counts_accurate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = _make_conn(tmp)
            _insert_session(conn)
            obl = _make_obligation()
            SqliteObligationRepository(conn).upsert(obl)
            on_obligation_upsert(conn, obl)

            for i, status in enumerate([
                AssertionStatus.SUPPORTED,
                AssertionStatus.CONFIRMED,
                AssertionStatus.SPECULATIVE,
                AssertionStatus.REFUTED,
            ]):
                a = _make_assertion(
                    assertion_id=f"asr-{i}",
                    obligation_id=obl.id,
                    status=status,
                )
                SqliteAssertionRepository(conn).upsert(a)
                on_assertion_upsert(conn, a)

            row = conn.execute(
                "SELECT * FROM obligation_frontier WHERE obligation_id = ?",
                (obl.id,),
            ).fetchone()
            self.assertEqual(row["supported_assertion_count"], 1)
            self.assertEqual(row["confirmed_assertion_count"], 1)
            self.assertEqual(row["speculative_assertion_count"], 1)
            self.assertEqual(row["refuted_assertion_count"], 1)
            conn.close()


class TestSessionFrontier(unittest.TestCase):
    def test_session_frontier_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = _make_conn(tmp)
            _insert_session(conn)
            obl = _make_obligation()
            SqliteObligationRepository(conn).upsert(obl)
            on_obligation_upsert(conn, obl)

            row = conn.execute(
                "SELECT * FROM session_frontier WHERE session_id = ?",
                ("sess-1",),
            ).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row["dirty_obligation_count"], 1)
            conn.close()

    def test_repo_state_change_increments_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = _make_conn(tmp)
            _insert_session(conn)
            sync_session_frontier(conn, "sess-1")

            v1 = conn.execute(
                "SELECT frontier_version FROM session_frontier WHERE session_id = ?",
                ("sess-1",),
            ).fetchone()["frontier_version"]

            on_repo_state_change(conn, "sess-1")

            v2 = conn.execute(
                "SELECT frontier_version FROM session_frontier WHERE session_id = ?",
                ("sess-1",),
            ).fetchone()["frontier_version"]

            self.assertGreater(v2, v1)
            conn.close()


# ===========================================================================
# Backfill
# ===========================================================================

class TestBackfillIdempotency(unittest.TestCase):
    def _populate_session(self, conn: sqlite3.Connection) -> None:
        _insert_session(conn)
        obl_repo = SqliteObligationRepository(conn)
        asr_repo = SqliteAssertionRepository(conn)
        ev_repo = SqliteEvidenceRepository(conn)
        fam_repo = SqliteAttemptFamilyRepository(conn)

        obl = _make_obligation()
        obl_repo.upsert(obl)

        ev = _make_evidence(evidence_id="ev-1", path="src/main.py")
        ev_repo.create(ev)

        asr = _make_assertion(
            assertion_id="asr-1",
            obligation_id="obl-1",
            scope_ref="src/main.py",
            evidence_ids=["ev-1"],
            status=AssertionStatus.SUPPORTED,
        )
        asr_repo.upsert(asr)

        fam = _make_family(
            family_id="fam-1",
            obligation_id="obl-1",
            touched_scope=["src/main.py"],
        )
        fam_repo.upsert(fam)

    def test_rebuild_produces_correct_projections(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = _make_conn(tmp)
            self._populate_session(conn)

            rebuild_session_projections(conn, "sess-1")

            # assertion_evidence_links
            links = conn.execute(
                "SELECT * FROM assertion_evidence_links WHERE assertion_id = 'asr-1'"
            ).fetchall()
            self.assertEqual(len(links), 1)
            self.assertEqual(links[0]["evidence_id"], "ev-1")

            # path_subject_index
            path_entries = conn.execute(
                "SELECT * FROM path_subject_index WHERE session_id = 'sess-1'"
            ).fetchall()
            self.assertGreater(len(path_entries), 0)
            paths = {r["normalized_path"] for r in path_entries}
            self.assertIn("src/main.py", paths)

            # obligation_frontier
            frontier = conn.execute(
                "SELECT * FROM obligation_frontier WHERE obligation_id = 'obl-1'"
            ).fetchone()
            self.assertIsNotNone(frontier)
            self.assertEqual(frontier["dirty"], 1)
            self.assertEqual(frontier["supported_assertion_count"], 1)

            # session_frontier
            sf = conn.execute(
                "SELECT * FROM session_frontier WHERE session_id = 'sess-1'"
            ).fetchone()
            self.assertIsNotNone(sf)

            conn.close()

    def test_rebuild_idempotent(self) -> None:
        """Running rebuild multiple times yields the same result."""
        with tempfile.TemporaryDirectory() as tmp:
            conn = _make_conn(tmp)
            self._populate_session(conn)

            rebuild_session_projections(conn, "sess-1")
            snap1_links = conn.execute(
                "SELECT COUNT(*) FROM assertion_evidence_links WHERE session_id = 'sess-1'"
            ).fetchone()[0]
            snap1_paths = conn.execute(
                "SELECT COUNT(*) FROM path_subject_index WHERE session_id = 'sess-1'"
            ).fetchone()[0]

            rebuild_session_projections(conn, "sess-1")
            snap2_links = conn.execute(
                "SELECT COUNT(*) FROM assertion_evidence_links WHERE session_id = 'sess-1'"
            ).fetchone()[0]
            snap2_paths = conn.execute(
                "SELECT COUNT(*) FROM path_subject_index WHERE session_id = 'sess-1'"
            ).fetchone()[0]

            self.assertEqual(snap1_links, snap2_links)
            self.assertEqual(snap1_paths, snap2_paths)
            conn.close()

    def test_rebuild_three_times_same_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = _make_conn(tmp)
            self._populate_session(conn)

            for _ in range(3):
                rebuild_session_projections(conn, "sess-1")

            link_count = conn.execute(
                "SELECT COUNT(*) FROM assertion_evidence_links"
            ).fetchone()[0]
            path_count = conn.execute(
                "SELECT COUNT(*) FROM path_subject_index"
            ).fetchone()[0]
            frontier_count = conn.execute(
                "SELECT COUNT(*) FROM obligation_frontier"
            ).fetchone()[0]
            sf_count = conn.execute(
                "SELECT COUNT(*) FROM session_frontier"
            ).fetchone()[0]

            self.assertEqual(link_count, 1)
            self.assertGreater(path_count, 0)
            self.assertEqual(frontier_count, 1)
            self.assertEqual(sf_count, 1)
            conn.close()


class TestCorruptedProjectionRecovery(unittest.TestCase):
    def test_rebuild_after_partial_corruption(self) -> None:
        """If projection data is corrupted, rebuild recovers it."""
        with tempfile.TemporaryDirectory() as tmp:
            conn = _make_conn(tmp)
            _insert_session(conn)
            obl = _make_obligation()
            SqliteObligationRepository(conn).upsert(obl)

            ev = _make_evidence()
            SqliteEvidenceRepository(conn).create(ev)

            asr = _make_assertion(evidence_ids=["ev-1"])
            SqliteAssertionRepository(conn).upsert(asr)

            # Build projections
            rebuild_session_projections(conn, "sess-1")

            # Corrupt: delete half the projection data
            conn.execute("DELETE FROM assertion_evidence_links")
            conn.execute("DELETE FROM path_subject_index")

            # Verify corruption
            self.assertEqual(
                conn.execute("SELECT COUNT(*) FROM assertion_evidence_links").fetchone()[0], 0
            )

            # Rebuild should recover
            rebuild_session_projections(conn, "sess-1")

            links = conn.execute(
                "SELECT COUNT(*) FROM assertion_evidence_links"
            ).fetchone()[0]
            paths = conn.execute(
                "SELECT COUNT(*) FROM path_subject_index"
            ).fetchone()[0]

            self.assertGreater(links, 0)
            self.assertGreater(paths, 0)
            conn.close()


class TestMultiSessionBackfill(unittest.TestCase):
    def test_rebuild_all_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = _make_conn(tmp)

            for sid in ("sess-1", "sess-2"):
                _insert_session(conn, sid)
                obl = _make_obligation(session_id=sid, obligation_id=f"obl-{sid}")
                SqliteObligationRepository(conn).upsert(obl)
                ev = _make_evidence(session_id=sid, evidence_id=f"ev-{sid}", path="src/x.py")
                SqliteEvidenceRepository(conn).create(ev)
                asr = _make_assertion(
                    session_id=sid,
                    assertion_id=f"asr-{sid}",
                    obligation_id=f"obl-{sid}",
                    evidence_ids=[f"ev-{sid}"],
                )
                SqliteAssertionRepository(conn).upsert(asr)

            rebuild_projections(conn)

            for sid in ("sess-1", "sess-2"):
                sf = conn.execute(
                    "SELECT * FROM session_frontier WHERE session_id = ?", (sid,)
                ).fetchone()
                self.assertIsNotNone(sf, f"session_frontier missing for {sid}")

                frontier = conn.execute(
                    "SELECT * FROM obligation_frontier WHERE obligation_id = ?",
                    (f"obl-{sid}",),
                ).fetchone()
                self.assertIsNotNone(frontier, f"obligation_frontier missing for {sid}")

            conn.close()


class TestCanonicalProjectionConsistency(unittest.TestCase):
    """Verify projection data matches canonical data."""

    def test_evidence_links_match_assertion_evidence_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            conn = _make_conn(tmp)
            _insert_session(conn)
            obl = _make_obligation()
            SqliteObligationRepository(conn).upsert(obl)

            ev1 = _make_evidence(evidence_id="ev-1")
            ev2 = _make_evidence(evidence_id="ev-2", path="src/other.py")
            SqliteEvidenceRepository(conn).create(ev1)
            SqliteEvidenceRepository(conn).create(ev2)

            asr = _make_assertion(evidence_ids=["ev-1", "ev-2"])
            SqliteAssertionRepository(conn).upsert(asr)
            on_assertion_upsert(conn, asr)

            # Check projection matches canonical
            link_eids = {
                r["evidence_id"]
                for r in conn.execute(
                    "SELECT evidence_id FROM assertion_evidence_links WHERE assertion_id = ?",
                    (asr.id,),
                ).fetchall()
            }
            self.assertEqual(link_eids, set(asr.evidence_ids))
            conn.close()


if __name__ == "__main__":
    unittest.main()

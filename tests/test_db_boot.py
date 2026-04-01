"""Tests for Step 02: DB Boot / Versioned Migration Split.

Covers:
- SqliteRuntime boot-once semantics
- Versioned migration registry (schema_migrations table, upgrade path)
- SqliteUnitOfWork booted-connection mode
- Pragma configuration (busy_timeout, synchronous)
- Legacy DB upgrade (pre-registry -> registry)
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from egtsr_runtime.db.connection import get_connection
from egtsr_runtime.db.migrations import run_migrations
from egtsr_runtime.db.migrations.registry import (
    _ensure_schema_migrations_table,
    _get_applied_versions,
    _legacy_tables_exist,
    run_registry_migrations,
)
from egtsr_runtime.db.runtime import SqliteRuntime
from egtsr_runtime.db.uow import SqliteUnitOfWork
from egtsr_runtime.paths import ensure_runtime_dirs


class TestMigrationRegistry(unittest.TestCase):
    """Migration registry creates tables and tracks versions."""

    def test_fresh_db_creates_all_tables(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = ensure_runtime_dirs(tmp)
            conn = get_connection(paths.db_path)
            try:
                run_migrations(conn)
                tables = _get_table_names(conn)
            finally:
                conn.close()

        # Canonical tables
        for name in (
            "sessions", "repo_state", "obligations", "evidence",
            "assertions", "invalidation_tickets", "attempt_families",
            "verify_results", "capsules", "events",
        ):
            self.assertIn(name, tables, f"Missing canonical table: {name}")

        # Projection tables
        for name in (
            "assertion_evidence_links", "path_subject_index",
            "obligation_frontier", "session_frontier",
        ):
            self.assertIn(name, tables, f"Missing projection table: {name}")

        # Migration tracking table
        self.assertIn("schema_migrations", tables)

    def test_schema_migrations_records_versions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = ensure_runtime_dirs(tmp)
            conn = get_connection(paths.db_path)
            try:
                run_migrations(conn)
                applied = _get_applied_versions(conn)
            finally:
                conn.close()

        self.assertIn(1, applied)
        self.assertIn(2, applied)

    def test_migrations_idempotent(self) -> None:
        """Running migrations multiple times does not fail."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = ensure_runtime_dirs(tmp)
            conn = get_connection(paths.db_path)
            try:
                run_migrations(conn)
                run_migrations(conn)
                run_migrations(conn)
                applied = _get_applied_versions(conn)
            finally:
                conn.close()

        self.assertEqual(applied, {1, 2, 3, 4, 5, 6, 7})


class TestLegacyUpgrade(unittest.TestCase):
    """Pre-registry databases get upgraded correctly."""

    def test_legacy_db_gets_initial_marked_as_applied(self) -> None:
        """A DB that already has canonical tables but no schema_migrations
        gets migration 1 marked as applied without re-running it."""
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "legacy.db")
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row

            # Simulate legacy DB: create all canonical tables directly
            # (as they would exist in a pre-registry DB)
            from egtsr_runtime.db.migrations.m0001_initial import MIGRATION as m0001
            m0001.up(conn)
            conn.commit()
            self.assertTrue(_legacy_tables_exist(conn))

            # Now run registry migrations
            run_registry_migrations(conn)

            applied = _get_applied_versions(conn)
            self.assertIn(1, applied)
            self.assertIn(2, applied)
            self.assertIn(3, applied)

            # Projection tables should exist too
            tables = _get_table_names(conn)
            self.assertIn("assertion_evidence_links", tables)
            conn.close()


class TestSqliteRuntime(unittest.TestCase):
    """SqliteRuntime boot-once semantics."""

    def test_boot_returns_connection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = ensure_runtime_dirs(tmp)
            runtime = SqliteRuntime(paths.db_path)
            try:
                conn = runtime.boot()
                self.assertIsInstance(conn, sqlite3.Connection)
                self.assertTrue(runtime.booted)
            finally:
                runtime.shutdown()

    def test_boot_idempotent_returns_same_connection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = ensure_runtime_dirs(tmp)
            runtime = SqliteRuntime(paths.db_path)
            try:
                conn1 = runtime.boot()
                conn2 = runtime.boot()
                self.assertIs(conn1, conn2)
            finally:
                runtime.shutdown()

    def test_boot_runs_migrations_once(self) -> None:
        """Multiple boot() calls don't re-run migrations."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = ensure_runtime_dirs(tmp)
            runtime = SqliteRuntime(paths.db_path)
            try:
                conn = runtime.boot()
                applied_before = _get_applied_versions(conn)
                runtime.boot()
                applied_after = _get_applied_versions(conn)
                self.assertEqual(applied_before, applied_after)
            finally:
                runtime.shutdown()

    def test_migration_runs_once_across_100_uow_requests(self) -> None:
        """Core completion criterion: 100 UoW requests, migration executes once."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = ensure_runtime_dirs(tmp)
            runtime = SqliteRuntime(paths.db_path)
            try:
                conn = runtime.boot()

                # Count migration records — should be exactly 2 (m0001 + m0002)
                count_before = conn.execute(
                    "SELECT COUNT(*) FROM schema_migrations"
                ).fetchone()[0]

                for _ in range(100):
                    uow = SqliteUnitOfWork(conn)
                    with uow:
                        uow.conn.execute("SELECT 1")

                count_after = conn.execute(
                    "SELECT COUNT(*) FROM schema_migrations"
                ).fetchone()[0]

                self.assertEqual(count_before, count_after)
                self.assertEqual(count_after, 7)
            finally:
                runtime.shutdown()

    def test_shutdown_closes_connection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = ensure_runtime_dirs(tmp)
            runtime = SqliteRuntime(paths.db_path)
            runtime.boot()
            runtime.shutdown()
            self.assertFalse(runtime.booted)

    def test_connection_raises_before_boot(self) -> None:
        runtime = SqliteRuntime("/tmp/nonexistent.db")
        with self.assertRaises(RuntimeError):
            runtime.connection()


class TestUnitOfWorkBootedMode(unittest.TestCase):
    """SqliteUnitOfWork with a pre-booted connection."""

    def test_booted_uow_does_not_close_connection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = ensure_runtime_dirs(tmp)
            runtime = SqliteRuntime(paths.db_path)
            try:
                conn = runtime.boot()

                uow = SqliteUnitOfWork(conn)
                with uow:
                    uow.conn.execute("SELECT 1")

                # Connection should still be usable after UoW exits
                result = conn.execute("SELECT 1").fetchone()
                self.assertEqual(result[0], 1)
            finally:
                runtime.shutdown()

    def test_booted_uow_has_repositories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            paths = ensure_runtime_dirs(tmp)
            runtime = SqliteRuntime(paths.db_path)
            try:
                conn = runtime.boot()
                uow = SqliteUnitOfWork(conn)
                with uow:
                    self.assertIsNotNone(uow.sessions)
                    self.assertIsNotNone(uow.obligations)
                    self.assertIsNotNone(uow.evidence)
            finally:
                runtime.shutdown()

    def test_legacy_uow_still_works(self) -> None:
        """Legacy path (path-based UoW) still opens, migrates, and closes."""
        with tempfile.TemporaryDirectory() as tmp:
            paths = ensure_runtime_dirs(tmp)
            with SqliteUnitOfWork(paths) as uow:
                tables = _get_table_names(uow.conn)
                self.assertIn("sessions", tables)
                self.assertIn("schema_migrations", tables)


class TestPragmaConfiguration(unittest.TestCase):
    """Connection pragmas are set correctly."""

    def test_busy_timeout_set(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "test.db")
            conn = get_connection(db_path)
            try:
                val = conn.execute("PRAGMA busy_timeout;").fetchone()[0]
                self.assertEqual(val, 5000)
            finally:
                conn.close()

    def test_synchronous_normal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "test.db")
            conn = get_connection(db_path)
            try:
                val = conn.execute("PRAGMA synchronous;").fetchone()[0]
                # synchronous=NORMAL is value 1
                self.assertEqual(val, 1)
            finally:
                conn.close()

    def test_wal_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "test.db")
            conn = get_connection(db_path)
            try:
                val = conn.execute("PRAGMA journal_mode;").fetchone()[0]
                self.assertEqual(val.lower(), "wal")
            finally:
                conn.close()

    def test_foreign_keys_on(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "test.db")
            conn = get_connection(db_path)
            try:
                val = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
                self.assertEqual(val, 1)
            finally:
                conn.close()


def _get_table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    return {row[0] for row in rows}


if __name__ == "__main__":
    unittest.main()

import sqlite3
import tempfile
import unittest
from pathlib import Path

from egtsr_runtime.db.connection import get_connection
from egtsr_runtime.db.migrations import run_migrations
from egtsr_runtime.paths import ensure_runtime_dirs


class DbMigrationTests(unittest.TestCase):
    def test_run_migrations_creates_all_tables(self) -> None:
        expected_tables = {
            "assertions",
            "attempt_families",
            "capsules",
            "events",
            "evidence",
            "invalidation_tickets",
            "obligations",
            "repo_state",
            "sessions",
            "verify_results",
        }

        with tempfile.TemporaryDirectory() as tmp_dir:
            paths = ensure_runtime_dirs(tmp_dir)
            conn = get_connection(paths.db_path)
            try:
                run_migrations(conn)
                rows = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            finally:
                conn.close()

        table_names = {row[0] for row in rows}
        self.assertTrue(expected_tables.issubset(table_names))

    def test_connection_configures_wal_and_foreign_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = Path(tmp_dir) / "runtime.db"
            conn = get_connection(str(db_path))
            try:
                journal_mode = conn.execute("PRAGMA journal_mode;").fetchone()[0]
                foreign_keys = conn.execute("PRAGMA foreign_keys;").fetchone()[0]
                self.assertEqual(journal_mode.lower(), "wal")
                self.assertEqual(foreign_keys, 1)
                self.assertIs(conn.row_factory, sqlite3.Row)
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()

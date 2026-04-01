from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest

from egtsr_runtime.constants import (
    DB_FILENAME,
    LAST_GOOD_CAPSULE,
    LOG_FILENAME,
    RESUME_GATE,
)
from egtsr_runtime.db.migrations import run_migrations
from egtsr_runtime.ops.health import HealthChecker
from egtsr_runtime.ops.recovery_cli import RecoveryCLI


def _make_valid_db(db_path: str) -> None:
    conn = sqlite3.connect(db_path)
    run_migrations(conn)
    conn.close()


def _resolve_egtsr_dir(repo_root: str) -> str:
    from egtsr_runtime.runtime_locator import resolve_project_dir

    return str(resolve_project_dir(repo_root))


def _make_valid_egtsr(tmp: str) -> tuple[str, str, str]:
    """Create valid runtime artifacts in the global shard for repo_root.

    Returns (repo_root, egtsr_dir, db_path).
    """
    repo_root = tmp
    egtsr_dir = _resolve_egtsr_dir(tmp)
    os.makedirs(egtsr_dir, exist_ok=True)

    db_path = os.path.join(egtsr_dir, DB_FILENAME)
    _make_valid_db(db_path)

    for artifact in [RESUME_GATE, LAST_GOOD_CAPSULE]:
        with open(os.path.join(egtsr_dir, artifact), "w") as f:
            json.dump({}, f)

    # log file
    open(os.path.join(egtsr_dir, LOG_FILENAME), "a").close()

    return repo_root, egtsr_dir, db_path


def _make_hooks_config(repo_root: str) -> None:
    claude_dir = os.path.join(repo_root, ".claude")
    os.makedirs(claude_dir, exist_ok=True)
    hooks = {
        "hooks": {
            "SessionStart": [{"type": "command", "command": "python3 -m egtsr_runtime.hooks.entrypoint session_start"}],
            "UserPromptSubmit": [{"type": "command", "command": "python3 -m egtsr_runtime.hooks.entrypoint user_prompt_submit"}],
            "PostToolUse": [{"type": "command", "command": "python3 -m egtsr_runtime.hooks.entrypoint post_tool_use"}],
            "SessionEnd": [{"type": "command", "command": "python3 -m egtsr_runtime.hooks.entrypoint session_end"}],
        }
    }
    with open(os.path.join(claude_dir, "hooks.json"), "w") as f:
        json.dump(hooks, f)


def _make_settings_local_config(repo_root: str) -> None:
    claude_dir = os.path.join(repo_root, ".claude")
    os.makedirs(claude_dir, exist_ok=True)
    hooks = {
        "hooks": {
            "SessionStart": [{"matcher": "", "hooks": [{"type": "command", "command": "python3 -m egtsr_runtime.hooks.entrypoint session_start"}]}],
            "UserPromptSubmit": [{"matcher": "", "hooks": [{"type": "command", "command": "python3 -m egtsr_runtime.hooks.entrypoint user_prompt_submit"}]}],
            "PostToolUse": [{"matcher": "", "hooks": [{"type": "command", "command": "python3 -m egtsr_runtime.hooks.entrypoint post_tool_use"}]}],
            "SessionEnd": [{"matcher": "", "hooks": [{"type": "command", "command": "python3 -m egtsr_runtime.hooks.entrypoint session_end"}]}],
        }
    }
    with open(os.path.join(claude_dir, "settings.local.json"), "w") as f:
        json.dump(hooks, f)


class TestRecoveryCLI(unittest.TestCase):
    def setUp(self):
        self._egtsr_home_tmp = tempfile.TemporaryDirectory()
        self._orig_egtsr_home = os.environ.get("EGTSR_HOME")
        os.environ["EGTSR_HOME"] = self._egtsr_home_tmp.name

    def tearDown(self):
        if self._orig_egtsr_home is not None:
            os.environ["EGTSR_HOME"] = self._orig_egtsr_home
        else:
            os.environ.pop("EGTSR_HOME", None)
        self._egtsr_home_tmp.cleanup()

    def test_doctor_healthy(self):
        """Doctor with valid DB/artifacts returns no issues"""
        with tempfile.TemporaryDirectory() as tmp:
            _make_valid_egtsr(tmp)
            _make_hooks_config(tmp)
            cli = RecoveryCLI()
            result = cli.doctor(tmp)
        self.assertIn("issues", result)
        self.assertIn("checks", result)
        self.assertEqual(result["issues"], [])

    def test_doctor_missing_db(self):
        """Doctor detects missing DB"""
        with tempfile.TemporaryDirectory() as tmp:
            # Don't create any artifacts — doctor should detect missing DB
            cli = RecoveryCLI()
            result = cli.doctor(tmp)
        issues = result["issues"]
        self.assertTrue(any("DB" in i or "db" in i.lower() for i in issues))

    def test_doctor_no_unsafe_unblock(self):
        """Doctor result has no unblock/force actions"""
        with tempfile.TemporaryDirectory() as tmp:
            _make_valid_egtsr(tmp)
            _make_hooks_config(tmp)
            cli = RecoveryCLI()
            result = cli.doctor(tmp)
        result_str = json.dumps(result).lower()
        self.assertNotIn("force", result_str)
        self.assertNotIn("unblock", result_str)
        self.assertNotIn("unsafe", result_str)

    def test_doctor_accepts_settings_local_hooks(self):
        """Doctor accepts plugin-installed settings.local.json hook config."""
        with tempfile.TemporaryDirectory() as tmp:
            _make_valid_egtsr(tmp)
            _make_settings_local_config(tmp)
            cli = RecoveryCLI()
            result = cli.doctor(tmp)
        self.assertEqual(result["issues"], [])


class TestResetToCheckpoint(unittest.TestCase):
    def setUp(self):
        self._egtsr_home_tmp = tempfile.TemporaryDirectory()
        self._orig_egtsr_home = os.environ.get("EGTSR_HOME")
        os.environ["EGTSR_HOME"] = self._egtsr_home_tmp.name

    def tearDown(self):
        if self._orig_egtsr_home is not None:
            os.environ["EGTSR_HOME"] = self._orig_egtsr_home
        else:
            os.environ.pop("EGTSR_HOME", None)
        self._egtsr_home_tmp.cleanup()

    def test_reset_no_db(self):
        """Reset returns False when DB is missing"""
        with tempfile.TemporaryDirectory() as tmp:
            cli = RecoveryCLI()
            result = cli.reset_to_checkpoint(tmp)
        self.assertFalse(result["reset"])
        self.assertIn("not found", result["detail"].lower())

    def test_reset_clears_stale_tickets(self):
        """Reset clears stale invalidation tickets"""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root, egtsr_dir, db_path = _make_valid_egtsr(tmp)
            conn = sqlite3.connect(db_path)
            # Insert a session and a stale ticket
            conn.execute(
                "INSERT INTO sessions (id, repo_root, status, created_at, updated_at) "
                "VALUES ('s1', ?, 'ended', '2025-01-01', '2025-01-01')",
                (tmp,),
            )
            conn.execute(
                "INSERT INTO invalidation_tickets "
                "(id, session_id, subject_type, subject_id, trigger_kind, status, created_at, updated_at) "
                "VALUES ('t1', 's1', 'assertion', 'a1', 'file_change', 'stale', '2025-01-01', '2025-01-01')"
            )
            conn.commit()
            conn.close()

            cli = RecoveryCLI()
            result = cli.reset_to_checkpoint(tmp)
        self.assertTrue(result["reset"])
        self.assertEqual(result["cleared"]["stale_tickets"], 1)

    def test_reset_clears_failed_attempts(self):
        """Reset clears failed attempt families"""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root, egtsr_dir, db_path = _make_valid_egtsr(tmp)
            conn = sqlite3.connect(db_path)
            conn.execute(
                "INSERT INTO sessions (id, repo_root, status, created_at, updated_at) "
                "VALUES ('s1', ?, 'ended', '2025-01-01', '2025-01-01')",
                (tmp,),
            )
            conn.execute(
                "INSERT INTO attempt_families "
                "(id, session_id, signature, last_outcome, fail_count, created_at, updated_at) "
                "VALUES ('af1', 's1', 'sig1', 'fail', 3, '2025-01-01', '2025-01-01')"
            )
            conn.commit()
            conn.close()

            cli = RecoveryCLI()
            result = cli.reset_to_checkpoint(tmp)
        self.assertTrue(result["reset"])
        self.assertEqual(result["cleared"]["failed_attempts"], 1)

    def test_reset_resets_gate(self):
        """Reset rewrites resume gate file"""
        with tempfile.TemporaryDirectory() as tmp:
            repo_root, egtsr_dir, db_path = _make_valid_egtsr(tmp)
            cli = RecoveryCLI()
            result = cli.reset_to_checkpoint(tmp)
        self.assertTrue(result["reset"])
        self.assertEqual(result["cleared"]["gate_reset"], 1)


class TestInspectCorruption(unittest.TestCase):
    def setUp(self):
        self._egtsr_home_tmp = tempfile.TemporaryDirectory()
        self._orig_egtsr_home = os.environ.get("EGTSR_HOME")
        os.environ["EGTSR_HOME"] = self._egtsr_home_tmp.name

    def tearDown(self):
        if self._orig_egtsr_home is not None:
            os.environ["EGTSR_HOME"] = self._orig_egtsr_home
        else:
            os.environ.pop("EGTSR_HOME", None)
        self._egtsr_home_tmp.cleanup()

    def test_inspect_no_db(self):
        """Inspect returns error when DB is missing"""
        with tempfile.TemporaryDirectory() as tmp:
            cli = RecoveryCLI()
            result = cli.inspect_corruption(tmp)
        self.assertEqual(result["integrity"], "error")
        self.assertTrue(len(result["anomalies"]) > 0)

    def test_inspect_healthy_db(self):
        """Inspect on healthy DB returns ok"""
        with tempfile.TemporaryDirectory() as tmp:
            _make_valid_egtsr(tmp)
            cli = RecoveryCLI()
            result = cli.inspect_corruption(tmp)
        self.assertEqual(result["integrity"], "ok")
        self.assertEqual(result["anomalies"], [])
        # All tables should be readable
        for table, count in result["tables"].items():
            self.assertGreaterEqual(count, 0, f"table {table} unreadable")

    def test_inspect_corrupt_db(self):
        """Inspect detects corrupt DB"""
        with tempfile.TemporaryDirectory() as tmp:
            _, egtsr_dir, db_path = _make_valid_egtsr(tmp)
            # Corrupt the DB
            with open(db_path, "w") as f:
                f.write("not a sqlite database!!!")
            cli = RecoveryCLI()
            result = cli.inspect_corruption(tmp)
        self.assertNotEqual(result["integrity"], "ok")

    def test_inspect_orphaned_obligations(self):
        """Inspect detects orphaned obligations"""
        with tempfile.TemporaryDirectory() as tmp:
            _, egtsr_dir, db_path = _make_valid_egtsr(tmp)
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA foreign_keys=OFF;")
            conn.execute(
                "INSERT INTO obligations "
                "(id, session_id, source, statement, priority, status, created_at, updated_at) "
                "VALUES ('o1', 'nonexistent', 'user', 'test', 50, 'active', '2025-01-01', '2025-01-01')"
            )
            conn.commit()
            conn.close()

            cli = RecoveryCLI()
            result = cli.inspect_corruption(tmp)
        self.assertTrue(
            any("orphaned obligations" in a for a in result["anomalies"])
        )


class TestHealthChecker(unittest.TestCase):
    """HealthChecker tests — these pass egtsr_dir directly, no locator needed."""

    def test_health_checker_all_ok(self):
        """HealthChecker with valid setup returns overall=True"""
        with tempfile.TemporaryDirectory() as tmp:
            egtsr_dir = tmp
            db_path = os.path.join(egtsr_dir, DB_FILENAME)
            _make_valid_db(db_path)
            for artifact in [RESUME_GATE, LAST_GOOD_CAPSULE]:
                with open(os.path.join(egtsr_dir, artifact), "w") as f:
                    json.dump({}, f)
            open(os.path.join(egtsr_dir, LOG_FILENAME), "a").close()

            checker = HealthChecker()
            result = checker.check(db_path, egtsr_dir)
        self.assertTrue(result["db_ok"])
        self.assertTrue(result["gate_ok"])
        self.assertTrue(result["capsule_ok"])
        self.assertTrue(result["dirs_ok"])
        self.assertTrue(result["log_ok"])
        self.assertTrue(result["overall"])
        self.assertEqual(result["issues"], [])
        self.assertEqual(result["warnings"], [])

    def test_health_checker_corrupt_db(self):
        """HealthChecker detects corrupt DB"""
        with tempfile.TemporaryDirectory() as tmp:
            egtsr_dir = tmp
            db_path = os.path.join(egtsr_dir, DB_FILENAME)
            _make_valid_db(db_path)
            for artifact in [RESUME_GATE, LAST_GOOD_CAPSULE]:
                with open(os.path.join(egtsr_dir, artifact), "w") as f:
                    json.dump({}, f)
            # corrupt the DB
            with open(db_path, "w") as f:
                f.write("not a sqlite database!!!")
            checker = HealthChecker()
            result = checker.check(db_path, egtsr_dir)
        self.assertFalse(result["db_ok"])
        self.assertFalse(result["overall"])
        self.assertTrue(len(result["issues"]) > 0)

    def test_health_checker_missing_gate(self):
        """HealthChecker detects missing resume_gate.json as soft warning"""
        with tempfile.TemporaryDirectory() as tmp:
            egtsr_dir = tmp
            db_path = os.path.join(egtsr_dir, DB_FILENAME)
            _make_valid_db(db_path)
            # Only create capsule, not gate
            with open(os.path.join(egtsr_dir, LAST_GOOD_CAPSULE), "w") as f:
                json.dump({}, f)
            open(os.path.join(egtsr_dir, LOG_FILENAME), "a").close()
            checker = HealthChecker()
            result = checker.check(db_path, egtsr_dir)
        self.assertFalse(result["gate_ok"])
        # JSON artifacts are export-only; overall health still passes
        self.assertTrue(result["overall"])
        self.assertTrue(len(result["warnings"]) > 0)

    def test_health_checker_missing_capsule(self):
        """HealthChecker detects missing capsule JSON as soft warning"""
        with tempfile.TemporaryDirectory() as tmp:
            egtsr_dir = tmp
            db_path = os.path.join(egtsr_dir, DB_FILENAME)
            _make_valid_db(db_path)
            # Only create gate, not capsule
            with open(os.path.join(egtsr_dir, RESUME_GATE), "w") as f:
                json.dump({}, f)
            open(os.path.join(egtsr_dir, LOG_FILENAME), "a").close()
            checker = HealthChecker()
            result = checker.check(db_path, egtsr_dir)
        self.assertFalse(result["capsule_ok"])
        # JSON artifacts are export-only; overall health still passes
        self.assertTrue(result["overall"])
        self.assertTrue(len(result["warnings"]) > 0)


if __name__ == "__main__":
    unittest.main()

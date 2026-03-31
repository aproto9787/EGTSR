from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import unittest

from egtsr_runtime.constants import (
    DB_FILENAME,
    EGTSR_DIR_NAME,
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


def _make_valid_egtsr(tmp: str) -> tuple[str, str, str]:
    """Create a valid .egtsr directory with required artifacts. Returns (repo_root, egtsr_dir, db_path)."""
    repo_root = tmp
    egtsr_dir = os.path.join(tmp, EGTSR_DIR_NAME)
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
            egtsr_dir = os.path.join(tmp, EGTSR_DIR_NAME)
            os.makedirs(egtsr_dir)
            # no DB created
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

    def test_health_checker_all_ok(self):
        """HealthChecker with valid setup returns overall=True"""
        with tempfile.TemporaryDirectory() as tmp:
            _, egtsr_dir, db_path = _make_valid_egtsr(tmp)
            checker = HealthChecker()
            result = checker.check(db_path, egtsr_dir)
        self.assertTrue(result["db_ok"])
        self.assertTrue(result["gate_ok"])
        self.assertTrue(result["capsule_ok"])
        self.assertTrue(result["dirs_ok"])
        self.assertTrue(result["log_ok"])
        self.assertTrue(result["overall"])
        self.assertEqual(result["issues"], [])

    def test_health_checker_corrupt_db(self):
        """HealthChecker detects corrupt DB"""
        with tempfile.TemporaryDirectory() as tmp:
            _, egtsr_dir, db_path = _make_valid_egtsr(tmp)
            # corrupt the DB
            with open(db_path, "w") as f:
                f.write("not a sqlite database!!!")
            checker = HealthChecker()
            result = checker.check(db_path, egtsr_dir)
        self.assertFalse(result["db_ok"])
        self.assertFalse(result["overall"])
        self.assertTrue(len(result["issues"]) > 0)

    def test_health_checker_missing_gate(self):
        """HealthChecker detects missing resume_gate.json"""
        with tempfile.TemporaryDirectory() as tmp:
            _, egtsr_dir, db_path = _make_valid_egtsr(tmp)
            os.remove(os.path.join(egtsr_dir, RESUME_GATE))
            checker = HealthChecker()
            result = checker.check(db_path, egtsr_dir)
        self.assertFalse(result["gate_ok"])
        self.assertFalse(result["overall"])

    def test_health_checker_missing_capsule(self):
        """HealthChecker detects missing last_good_decision_capsule.json"""
        with tempfile.TemporaryDirectory() as tmp:
            _, egtsr_dir, db_path = _make_valid_egtsr(tmp)
            os.remove(os.path.join(egtsr_dir, LAST_GOOD_CAPSULE))
            checker = HealthChecker()
            result = checker.check(db_path, egtsr_dir)
        self.assertFalse(result["capsule_ok"])
        self.assertFalse(result["overall"])


if __name__ == "__main__":
    unittest.main()

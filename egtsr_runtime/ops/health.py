from __future__ import annotations

import json
import os
import sqlite3

from egtsr_runtime.constants import (
    DB_FILENAME,
    EGTSR_DIR_NAME,
    LAST_GOOD_CAPSULE,
    LOG_FILENAME,
    RESUME_GATE,
)


class HealthChecker:
    def check(self, db_path: str, egtsr_dir: str) -> dict:
        """Check runtime health. Returns dict with check results.

        Checks:
        1. DB readable (can open + query sessions table)
        2. resume_gate.json exists and valid JSON
        3. last_good_decision_capsule.json exists and valid JSON
        4. .egtsr/ directory structure intact
        5. log file writable

        Returns: {"db_ok": bool, "gate_ok": bool, "capsule_ok": bool,
                  "dirs_ok": bool, "log_ok": bool, "overall": bool, "issues": [str]}
        """
        issues: list[str] = []

        db_ok = self._check_db(db_path, issues)
        gate_ok = self._check_json_file(
            os.path.join(egtsr_dir, RESUME_GATE), "resume_gate", issues
        )
        capsule_ok = self._check_json_file(
            os.path.join(egtsr_dir, LAST_GOOD_CAPSULE), "last_good_capsule", issues
        )
        dirs_ok = self._check_dirs(egtsr_dir, issues)
        log_ok = self._check_log_writable(os.path.join(egtsr_dir, LOG_FILENAME), issues)

        overall = db_ok and gate_ok and capsule_ok and dirs_ok and log_ok
        return {
            "db_ok": db_ok,
            "gate_ok": gate_ok,
            "capsule_ok": capsule_ok,
            "dirs_ok": dirs_ok,
            "log_ok": log_ok,
            "overall": overall,
            "issues": issues,
        }

    @staticmethod
    def _check_db(db_path: str, issues: list[str]) -> bool:
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("SELECT 1 FROM sessions LIMIT 1")
            conn.close()
            return True
        except Exception as exc:
            issues.append(f"db_not_readable: {exc}")
            return False

    @staticmethod
    def _check_json_file(path: str, label: str, issues: list[str]) -> bool:
        if not os.path.exists(path):
            issues.append(f"{label}_missing: {path}")
            return False
        try:
            with open(path) as f:
                json.load(f)
            return True
        except Exception as exc:
            issues.append(f"{label}_invalid_json: {exc}")
            return False

    @staticmethod
    def _check_dirs(egtsr_dir: str, issues: list[str]) -> bool:
        if not os.path.isdir(egtsr_dir):
            issues.append(f"egtsr_dir_missing: {egtsr_dir}")
            return False
        return True

    @staticmethod
    def _check_log_writable(log_path: str, issues: list[str]) -> bool:
        try:
            with open(log_path, "a"):
                pass
            return True
        except Exception as exc:
            issues.append(f"log_not_writable: {exc}")
            return False

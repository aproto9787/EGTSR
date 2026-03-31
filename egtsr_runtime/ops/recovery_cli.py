from __future__ import annotations

import json
import os
import sqlite3

from egtsr_runtime.constants import (
    DB_FILENAME,
    EGTSR_DIR_NAME,
    LAST_GOOD_CAPSULE,
    PHASE1_HOOKS,
    RESUME_GATE,
)
from egtsr_runtime.ops.health import HealthChecker


class RecoveryCLI:
    def doctor(self, repo_root: str) -> dict:
        """Run full diagnosis. Safe actions only, NO unsafe unblock.

        Returns: {"checks": [...], "issues": [...], "safe_fixes": [...]}
        """
        egtsr_dir = os.path.join(repo_root, EGTSR_DIR_NAME)
        db_path = os.path.join(egtsr_dir, DB_FILENAME)

        checks = []
        issues: list[str] = []
        safe_fixes: list[str] = []

        db_result = self._check_db(db_path)
        checks.append(db_result)
        if not db_result["ok"]:
            issues.append(db_result["detail"])
            safe_fixes.append("re-run egtsr SessionStart hook to recreate DB")

        artifacts_result = self._check_artifacts(egtsr_dir)
        checks.append(artifacts_result)
        if not artifacts_result["ok"]:
            issues.extend(artifacts_result.get("missing", []))

        hooks_result = self._check_hooks_config(repo_root)
        checks.append(hooks_result)
        if not hooks_result["ok"]:
            issues.append(hooks_result["detail"])
            safe_fixes.append("install scaffolds/standalone/.claude/hooks.json")

        return {"checks": checks, "issues": issues, "safe_fixes": safe_fixes}

    def _check_db(self, db_path: str) -> dict:
        if not os.path.exists(db_path):
            return {"name": "db", "ok": False, "detail": f"DB file missing: {db_path}"}
        try:
            conn = sqlite3.connect(db_path)
            conn.execute("SELECT 1 FROM sessions LIMIT 1")
            conn.close()
            return {"name": "db", "ok": True, "detail": "DB readable"}
        except Exception as exc:
            return {"name": "db", "ok": False, "detail": f"DB not readable: {exc}"}

    def _check_artifacts(self, egtsr_dir: str) -> dict:
        missing = []
        for artifact in [RESUME_GATE, LAST_GOOD_CAPSULE]:
            path = os.path.join(egtsr_dir, artifact)
            if not os.path.exists(path):
                missing.append(f"missing artifact: {artifact}")
        ok = len(missing) == 0
        return {"name": "artifacts", "ok": ok, "missing": missing}

    def _check_hooks_config(self, repo_root: str) -> dict:
        hooks_path = os.path.join(repo_root, ".claude", "hooks.json")
        if not os.path.exists(hooks_path):
            return {
                "name": "hooks_config",
                "ok": False,
                "detail": f"hooks.json missing: {hooks_path}",
            }
        try:
            with open(hooks_path) as f:
                config = json.load(f)
            hooks = config.get("hooks", {})
            missing_hooks = [h for h in PHASE1_HOOKS if h not in hooks]
            if missing_hooks:
                return {
                    "name": "hooks_config",
                    "ok": False,
                    "detail": f"missing hooks: {missing_hooks}",
                }
            return {"name": "hooks_config", "ok": True, "detail": "all hooks configured"}
        except Exception as exc:
            return {"name": "hooks_config", "ok": False, "detail": f"hooks.json invalid: {exc}"}


def main() -> None:
    import sys

    cli = RecoveryCLI()
    repo_root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    result = cli.doctor(repo_root)
    print(json.dumps(result, indent=2))
    if result["issues"]:
        sys.exit(1)

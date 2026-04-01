from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone

from egtsr_runtime.constants import (
    DB_FILENAME,
    LAST_GOOD_CAPSULE,
    PHASE1_HOOKS,
    RESUME_GATE,
)

_ALL_TABLES = (
    "sessions",
    "repo_state",
    "obligations",
    "evidence",
    "assertions",
    "invalidation_tickets",
    "attempt_families",
    "verify_results",
    "capsules",
    "events",
)

_EXPECTED_HOOK_COMMANDS = {
    "SessionStart": "python3 -m egtsr_runtime.hooks.entrypoint session_start",
    "UserPromptSubmit": "python3 -m egtsr_runtime.hooks.entrypoint user_prompt_submit",
    "PostToolUse": "python3 -m egtsr_runtime.hooks.entrypoint post_tool_use",
    "SessionEnd": "python3 -m egtsr_runtime.hooks.entrypoint session_end",
}


class RecoveryCLI:
    def doctor(self, repo_root: str) -> dict:
        """Run full diagnosis. Safe actions only, NO unsafe unblock.

        Returns: {"checks": [...], "issues": [...], "safe_fixes": [...]}
        """
        from egtsr_runtime.runtime_locator import resolve_project_dir

        egtsr_dir = str(resolve_project_dir(repo_root))
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
        # JSON artifacts are export/debug only; missing artifacts are noted
        # but do not block overall health (DB is authoritative)

        hooks_result = self._check_hooks_config(repo_root)
        checks.append(hooks_result)
        if not hooks_result["ok"]:
            issues.append(hooks_result["detail"])
            safe_fixes.append("run `egtsr setup` to register EGTSR hooks")

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
        hooks_path = self._find_hooks_config(repo_root)
        if hooks_path is None:
            claude_dir = os.path.join(repo_root, ".claude")
            return {
                "name": "hooks_config",
                "ok": False,
                "detail": (
                    "hooks config missing: expected one of "
                    f"{os.path.join(claude_dir, 'settings.local.json')} or "
                    f"{os.path.join(claude_dir, 'hooks.json')}"
                ),
            }
        return self._validate_hooks_config(hooks_path)

    def _find_hooks_config(self, repo_root: str) -> str | None:
        claude_dir = os.path.join(repo_root, ".claude")
        for filename in ("settings.local.json", "hooks.json"):
            candidate = os.path.join(claude_dir, filename)
            if os.path.exists(candidate):
                return candidate
        return None

    def _validate_hooks_config(self, hooks_path: str) -> dict:
        if not os.path.exists(hooks_path):
            return {
                "name": "hooks_config",
                "ok": False,
                "detail": f"hooks config missing: {hooks_path}",
            }
        try:
            with open(hooks_path) as f:
                config = json.load(f)
            hooks = config.get("hooks", {})
            missing_hooks = [
                hook_name
                for hook_name in PHASE1_HOOKS
                if not self._has_registered_command(
                    hooks.get(hook_name),
                    _EXPECTED_HOOK_COMMANDS[hook_name],
                )
            ]
            if missing_hooks:
                return {
                    "name": "hooks_config",
                    "ok": False,
                    "detail": f"missing hooks in {hooks_path}: {missing_hooks}",
                }
            return {
                "name": "hooks_config",
                "ok": True,
                "detail": f"all hooks configured in {hooks_path}",
            }
        except Exception as exc:
            return {
                "name": "hooks_config",
                "ok": False,
                "detail": f"hooks config invalid ({hooks_path}): {exc}",
            }

    def reset_to_checkpoint(self, repo_root: str) -> dict:
        """Reset runtime state to last clean checkpoint.

        Clears stale invalidation tickets, resets gate state, and removes
        non-active session data.  This is a destructive operation — callers
        should confirm with the user first.

        Returns: {"reset": True/False, "detail": str, "cleared": {...}}
        """
        from egtsr_runtime.runtime_locator import resolve_project_dir

        egtsr_dir = str(resolve_project_dir(repo_root))
        db_path = os.path.join(egtsr_dir, DB_FILENAME)

        if not os.path.exists(db_path):
            return {"reset": False, "detail": f"DB not found: {db_path}", "cleared": {}}

        try:
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA foreign_keys=ON;")
        except Exception as exc:
            return {"reset": False, "detail": f"Cannot open DB: {exc}", "cleared": {}}

        cleared: dict[str, int] = {}
        try:
            # Clear stale invalidation tickets
            cur = conn.execute(
                "DELETE FROM invalidation_tickets WHERE status = 'stale'"
            )
            cleared["stale_tickets"] = cur.rowcount

            # Clear failed attempt families
            cur = conn.execute(
                "DELETE FROM attempt_families WHERE last_outcome = 'fail'"
            )
            cleared["failed_attempts"] = cur.rowcount

            # Reset gate file to empty
            gate_path = os.path.join(egtsr_dir, RESUME_GATE)
            if os.path.exists(gate_path):
                with open(gate_path, "w") as f:
                    json.dump({"reset_at": datetime.now(timezone.utc).isoformat()}, f)
                cleared["gate_reset"] = 1
            else:
                cleared["gate_reset"] = 0

            conn.commit()
        except Exception as exc:
            conn.rollback()
            conn.close()
            return {"reset": False, "detail": f"Reset failed: {exc}", "cleared": cleared}
        finally:
            conn.close()

        return {"reset": True, "detail": "Checkpoint reset complete", "cleared": cleared}

    def inspect_corruption(self, repo_root: str) -> dict:
        """Run DB integrity checks and anomaly detection.

        Returns: {"integrity": str, "tables": {...}, "anomalies": [...]}
        """
        from egtsr_runtime.runtime_locator import resolve_project_dir

        egtsr_dir = str(resolve_project_dir(repo_root))
        db_path = os.path.join(egtsr_dir, DB_FILENAME)

        if not os.path.exists(db_path):
            return {
                "integrity": "error",
                "detail": f"DB not found: {db_path}",
                "tables": {},
                "anomalies": ["DB file missing"],
            }

        try:
            conn = sqlite3.connect(db_path)
        except Exception as exc:
            return {
                "integrity": "error",
                "detail": f"Cannot open DB: {exc}",
                "tables": {},
                "anomalies": [f"Cannot open DB: {exc}"],
            }

        anomalies: list[str] = []

        # PRAGMA integrity_check
        try:
            rows = conn.execute("PRAGMA integrity_check;").fetchall()
            integrity = rows[0][0] if rows else "unknown"
            if integrity != "ok":
                anomalies.append(f"integrity_check: {integrity}")
        except Exception as exc:
            integrity = f"error: {exc}"
            anomalies.append(f"integrity_check failed: {exc}")

        # Table row counts
        tables: dict[str, int] = {}
        for table in _ALL_TABLES:
            try:
                row = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()  # noqa: S608
                tables[table] = row[0] if row else 0
            except Exception:
                tables[table] = -1
                anomalies.append(f"table '{table}' unreadable")

        # Anomaly detection: orphaned rows
        try:
            orphan_count = conn.execute(
                "SELECT COUNT(*) FROM obligations "
                "WHERE session_id NOT IN (SELECT id FROM sessions)"
            ).fetchone()
            if orphan_count and orphan_count[0] > 0:
                anomalies.append(
                    f"orphaned obligations: {orphan_count[0]} rows with missing session"
                )
        except Exception:
            pass

        try:
            orphan_evidence = conn.execute(
                "SELECT COUNT(*) FROM evidence "
                "WHERE session_id NOT IN (SELECT id FROM sessions)"
            ).fetchone()
            if orphan_evidence and orphan_evidence[0] > 0:
                anomalies.append(
                    f"orphaned evidence: {orphan_evidence[0]} rows with missing session"
                )
        except Exception:
            pass

        # Anomaly detection: sessions stuck in 'active' with old timestamps
        try:
            stuck = conn.execute(
                "SELECT COUNT(*) FROM sessions "
                "WHERE status = 'active' "
                "AND updated_at < datetime('now', '-24 hours')"
            ).fetchone()
            if stuck and stuck[0] > 0:
                anomalies.append(
                    f"stuck sessions: {stuck[0]} active sessions older than 24h"
                )
        except Exception:
            pass

        conn.close()

        return {
            "integrity": integrity,
            "tables": tables,
            "anomalies": anomalies,
        }

    @staticmethod
    def _has_registered_command(entries, expected_command: str) -> bool:
        if not isinstance(entries, list):
            return False
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            nested_hooks = entry.get("hooks")
            if isinstance(nested_hooks, list):
                if any(
                    isinstance(hook, dict)
                    and hook.get("type") == "command"
                    and hook.get("command") == expected_command
                    for hook in nested_hooks
                ):
                    return True
                continue
            if entry.get("type") == "command" and entry.get("command") == expected_command:
                return True
        return False


def main() -> None:
    import sys

    cli = RecoveryCLI()
    repo_root = sys.argv[1] if len(sys.argv) > 1 else os.getcwd()
    result = cli.doctor(repo_root)
    print(json.dumps(result, indent=2))
    if result["issues"]:
        sys.exit(1)

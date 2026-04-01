from __future__ import annotations

import json
import os
import sqlite3

from egtsr_runtime.constants import (
    DB_FILENAME,
    LAST_GOOD_CAPSULE,
    PHASE1_HOOKS,
    RESUME_GATE,
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

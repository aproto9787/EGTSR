"""Remove EGTSR hooks from a Claude Code project."""
from __future__ import annotations

import json
from pathlib import Path

_EGTSR_COMMANDS = {
    "SessionStart": "python3 -m egtsr_runtime.hooks.entrypoint session_start",
    "UserPromptSubmit": "python3 -m egtsr_runtime.hooks.entrypoint user_prompt_submit",
    "PostToolUse": "python3 -m egtsr_runtime.hooks.entrypoint post_tool_use",
    "SessionEnd": "python3 -m egtsr_runtime.hooks.entrypoint session_end",
}


def run_uninstall(project_dir: str = ".") -> None:
    """Remove EGTSR hook entries from .claude/settings.local.json."""
    project = Path(project_dir).expanduser().resolve()
    settings_path = project / ".claude" / "settings.local.json"
    if not settings_path.exists():
        print(f"No EGTSR settings found at {settings_path}")
        return

    data = json.loads(settings_path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {settings_path}")

    hooks = data.get("hooks")
    if not isinstance(hooks, dict):
        print(f"No hook configuration found in {settings_path}")
        return

    removed: list[str] = []
    for hook_name, command in _EGTSR_COMMANDS.items():
        entries = hooks.get(hook_name)
        if not isinstance(entries, list):
            continue
        filtered = []
        hook_removed = False
        for entry in entries:
            cleaned_entry, entry_removed = _remove_command(entry, command)
            hook_removed = hook_removed or entry_removed
            if cleaned_entry is not None:
                filtered.append(cleaned_entry)
        if filtered:
            hooks[hook_name] = filtered
        else:
            hooks.pop(hook_name, None)
        if hook_removed:
            removed.append(hook_name)

    data["hooks"] = hooks
    settings_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    if removed:
        print(f"✓ Removed EGTSR hooks from {settings_path}")
        print(f"  Hooks: {', '.join(removed)}")
    else:
        print(f"No EGTSR hooks found in {settings_path}")


def _remove_command(entry: object, command: str) -> tuple[object | None, bool]:
    if not isinstance(entry, dict):
        return entry, False

    if entry.get("type") == "command":
        if entry.get("command") == command:
            return None, True
        return entry, False

    nested_hooks = entry.get("hooks")
    if not isinstance(nested_hooks, list):
        return entry, False

    filtered_hooks = []
    removed = False
    for hook in nested_hooks:
        if isinstance(hook, dict) and hook.get("type") == "command" and hook.get("command") == command:
            removed = True
            continue
        filtered_hooks.append(hook)

    if not filtered_hooks:
        return None, removed

    updated = dict(entry)
    updated["hooks"] = filtered_hooks
    return updated, removed

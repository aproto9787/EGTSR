"""Register EGTSR hooks in a Claude Code project."""
from __future__ import annotations

import json
from pathlib import Path

_EGTSR_HOOKS = {
    "SessionStart": [{
        "matcher": "",
        "hooks": [{"type": "command", "command": "python3 -m egtsr_runtime.hooks.entrypoint session_start"}],
    }],
    "UserPromptSubmit": [{
        "matcher": "",
        "hooks": [{"type": "command", "command": "python3 -m egtsr_runtime.hooks.entrypoint user_prompt_submit"}],
    }],
    "PostToolUse": [{
        "matcher": "",
        "hooks": [{"type": "command", "command": "python3 -m egtsr_runtime.hooks.entrypoint post_tool_use"}],
    }],
    "SessionEnd": [{
        "matcher": "",
        "hooks": [{"type": "command", "command": "python3 -m egtsr_runtime.hooks.entrypoint session_end"}],
    }],
}


def run_setup(project_dir: str = ".") -> None:
    """Write .claude/settings.local.json with EGTSR hooks."""
    project = Path(project_dir).expanduser().resolve()
    claude_dir = project / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)

    settings_path = claude_dir / "settings.local.json"
    existing = _load_json_object(settings_path)
    hooks = existing.get("hooks")
    if not isinstance(hooks, dict):
        hooks = {}

    added: list[str] = []
    for hook_name, hook_config in _EGTSR_HOOKS.items():
        entries = hooks.get(hook_name)
        if not isinstance(entries, list):
            entries = []
        egtsr_command = hook_config[0]["hooks"][0]["command"]
        if any(command == egtsr_command for command in _iter_commands(entries)):
            hooks[hook_name] = entries
            continue
        entries.extend(json.loads(json.dumps(hook_config)))
        hooks[hook_name] = entries
        added.append(hook_name)

    existing["hooks"] = hooks
    settings_path.write_text(
        json.dumps(existing, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    if added:
        print(f"✓ EGTSR hooks registered in {settings_path}")
        print(f"  Hooks: {', '.join(added)}")
    else:
        print(f"✓ EGTSR hooks already registered in {settings_path}")
    print(f"\n  Start a new Claude Code session in {project} to activate.")


def _load_json_object(path: Path) -> dict:
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return data


def _iter_commands(entries: list[dict]) -> list[str]:
    commands: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        nested_hooks = entry.get("hooks")
        if isinstance(nested_hooks, list):
            for hook in nested_hooks:
                if isinstance(hook, dict) and hook.get("type") == "command" and isinstance(hook.get("command"), str):
                    commands.append(hook["command"])
            continue
        if entry.get("type") == "command" and isinstance(entry.get("command"), str):
            commands.append(entry["command"])
    return commands

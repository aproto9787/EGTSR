from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import PurePath
from typing import Any, cast

from egtsr_runtime.constants import PHASE1_HOOKS
from egtsr_runtime.hooks.envelopes import HookEnvelope

_REQUIRED_FIELDS = ("hook_event_name", "session_id", "cwd")
_PLUGIN_CACHE_MARKER = "/.claude/plugins/cache/"
_PLUGIN_MARKETPLACE_MARKER = "/.claude/plugins/marketplaces/"
_PROJECTS_MARKER = "/.claude/projects/"


def parse_hook_stdin(raw_text: str) -> HookEnvelope:
    """Parse raw JSON stdin into normalized HookEnvelope."""
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError("Malformed hook JSON") from exc

    if not isinstance(payload, dict):
        raise ValueError("Hook payload must be a JSON object")

    for field_name in _REQUIRED_FIELDS:
        value = payload.get(field_name)
        if not isinstance(value, str) or not value:
            raise ValueError(f"Missing required field: {field_name}")

    hook_event_name = payload["hook_event_name"]
    if hook_event_name not in PHASE1_HOOKS:
        raise ValueError(f"Unsupported hook event: {hook_event_name}")

    return HookEnvelope(
        version="1",
        received_at=datetime.now(timezone.utc).isoformat(),
        hook_event_name=cast(
            "SessionStart | UserPromptSubmit | PostToolUse | SessionEnd",
            hook_event_name,
        ),
        session_id=payload["session_id"],
        cwd=normalize_hook_cwd(payload["cwd"], _optional_str(payload, "transcript_path")),
        transcript_path=_optional_str(payload, "transcript_path"),
        permission_mode=_optional_str(payload, "permission_mode"),
        source=_optional_str(payload, "source"),
        tool_name=_optional_str(payload, "tool_name") if hook_event_name == "PostToolUse" else None,
        tool_use_id=_optional_str(payload, "tool_use_id") if hook_event_name == "PostToolUse" else None,
        prompt=_optional_str(payload, "prompt") if hook_event_name == "UserPromptSubmit" else None,
        raw=cast(dict[str, Any], payload),
    )


def normalize_hook_cwd(cwd: str, transcript_path: Any) -> str:
    fallback_cwd = _extract_cwd_from_transcript_path(transcript_path)
    if fallback_cwd and fallback_cwd != cwd:
        return fallback_cwd
    return cwd


def _extract_cwd_from_transcript_path(transcript_path: Any) -> str | None:
    # Claude hook cwd may point at plugin cache, so recover repo root from transcript path.
    if not isinstance(transcript_path, str) or not transcript_path or _PROJECTS_MARKER not in transcript_path:
        return None

    encoded_root = PurePath(transcript_path).parts
    try:
        projects_index = encoded_root.index("projects")
        encoded_root = encoded_root[projects_index + 1]
    except (ValueError, IndexError):
        return None

    if not encoded_root.startswith("-"):
        return None

    egtsr_home = os.environ.get("EGTSR_HOME")
    if egtsr_home:
        try:
            with open(os.path.join(egtsr_home, "manifest.json"), "r", encoding="utf-8") as fh:
                manifest = json.load(fh)
            projects = manifest.get("projects", {})
            if isinstance(projects, dict):
                for project in projects.values():
                    if not isinstance(project, dict):
                        continue
                    repo_root = project.get("repo_root")
                    if isinstance(repo_root, str) and repo_root.replace("/", "-") == encoded_root:
                        return repo_root
        except (OSError, json.JSONDecodeError, TypeError):
            pass

    decoded_root = encoded_root.replace("-", "/")
    return decoded_root or None


def _optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, cast

from egtsr_runtime.constants import PHASE1_HOOKS
from egtsr_runtime.hooks.envelopes import HookEnvelope

_REQUIRED_FIELDS = ("hook_event_name", "session_id", "cwd")


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
        cwd=payload["cwd"],
        transcript_path=_optional_str(payload, "transcript_path"),
        permission_mode=_optional_str(payload, "permission_mode"),
        source=_optional_str(payload, "source"),
        tool_name=_optional_str(payload, "tool_name") if hook_event_name == "PostToolUse" else None,
        tool_use_id=_optional_str(payload, "tool_use_id") if hook_event_name == "PostToolUse" else None,
        prompt=_optional_str(payload, "prompt") if hook_event_name == "UserPromptSubmit" else None,
        raw=cast(dict[str, Any], payload),
    )


def _optional_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None

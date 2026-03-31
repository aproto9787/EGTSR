from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(slots=True)
class HookEnvelope:
    version: str
    received_at: str
    hook_event_name: Literal["SessionStart", "UserPromptSubmit", "PostToolUse", "SessionEnd"]
    session_id: str
    cwd: str
    transcript_path: str | None
    permission_mode: str | None
    source: str | None
    tool_name: str | None
    tool_use_id: str | None
    prompt: str | None
    raw: dict[str, Any]

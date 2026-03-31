from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Protocol

from egtsr_runtime.ingest.excerpt import clip_excerpt
from egtsr_runtime.models import Evidence

if TYPE_CHECKING:
    from egtsr_runtime.hooks.envelopes import HookEnvelope


@dataclass(slots=True)
class IngestResult:
    evidence_ids: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)


class ToolNormalizer(Protocol):
    def normalize(self, envelope: "HookEnvelope") -> list[Evidence]: ...

    def changed_files(self, envelope: "HookEnvelope") -> list[str]: ...


class DefaultNormalizer:
    def normalize(self, envelope: "HookEnvelope") -> list[Evidence]:
        tool_input = get_tool_input(envelope)
        path = as_text(tool_input.get("file_path")) or None
        return [
            make_evidence(
                envelope,
                kind="tool_output",
                source_tool=envelope.tool_name or "Unknown",
                path=path,
                scope_kind="tool",
                scope_ref=envelope.tool_name or "unknown",
                polarity="positive",
                excerpt=clip_excerpt(summarize_response(get_tool_response(envelope))),
                metadata={
                    "tool_use_id": envelope.tool_use_id,
                    "unsupported_tool": True,
                },
            )
        ]

    def changed_files(self, envelope: "HookEnvelope") -> list[str]:
        tool_input = get_tool_input(envelope)
        path = as_text(tool_input.get("file_path"))
        return [path] if path else []


def get_normalizer(tool_name: str) -> ToolNormalizer:
    """Return appropriate normalizer for tool_name."""
    normalized_name = (tool_name or "").strip()
    if normalized_name == "Read":
        from egtsr_runtime.ingest.read_normalizer import ReadNormalizer

        return ReadNormalizer()
    if normalized_name == "Bash":
        from egtsr_runtime.ingest.bash_normalizer import BashNormalizer

        return BashNormalizer()
    if normalized_name == "Test":
        from egtsr_runtime.ingest.test_normalizer import TestNormalizer

        return TestNormalizer()
    if normalized_name in {"Write", "Edit", "Diff"}:
        from egtsr_runtime.ingest.diff_normalizer import DiffNormalizer

        return DiffNormalizer()
    return DefaultNormalizer()


def get_tool_input(envelope: "HookEnvelope") -> dict[str, Any]:
    tool_input = envelope.raw.get("tool_input")
    return tool_input if isinstance(tool_input, dict) else {}


def get_tool_response(envelope: "HookEnvelope") -> dict[str, Any]:
    tool_response = envelope.raw.get("tool_response")
    return tool_response if isinstance(tool_response, dict) else {}


def as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def summarize_response(tool_response: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("content", "stdout", "stderr", "output", "result", "message", "status"):
        text = as_text(tool_response.get(key)).strip()
        if text:
            parts.append(f"{key}: {text}")
    exit_code = tool_response.get("exit_code")
    if exit_code is not None:
        parts.append(f"exit_code: {exit_code}")
    if not parts and tool_response:
        parts.append(as_text(tool_response))
    return "\n".join(parts).strip()


def make_evidence(
    envelope: "HookEnvelope",
    *,
    kind: str,
    source_tool: str,
    path: str | None = None,
    scope_kind: str | None = None,
    scope_ref: str | None = None,
    polarity: str = "positive",
    excerpt: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Evidence:
    return Evidence(
        id=uuid.uuid4().hex,
        session_id=envelope.session_id,
        kind=kind,
        source_tool=source_tool,
        path=path,
        scope_kind=scope_kind,
        scope_ref=scope_ref,
        polarity=polarity,
        excerpt=excerpt,
        metadata=metadata or {},
        created_at=datetime.now(timezone.utc).isoformat(),
    )

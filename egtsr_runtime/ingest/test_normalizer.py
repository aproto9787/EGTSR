from __future__ import annotations

import re

from egtsr_runtime.ingest.excerpt import clip_excerpt
from egtsr_runtime.ingest.normalizer import as_text, get_tool_input, get_tool_response, make_evidence

_FAILURE_PATTERNS = (
    re.compile(r"\bFAIL(?:ED|URES?)?\b", re.IGNORECASE),
    re.compile(r"\bERROR\b", re.IGNORECASE),
)


class TestNormalizer:
    def normalize(self, envelope) -> list:
        """Create evidence from Test tool result."""
        tool_input = get_tool_input(envelope)
        tool_response = get_tool_response(envelope)
        command = as_text(tool_input.get("command") or tool_input.get("suite")).strip()
        stdout = as_text(tool_response.get("stdout") or tool_response.get("output")).strip()
        stderr = as_text(tool_response.get("stderr")).strip()
        exit_code = tool_response.get("exit_code")
        combined = "\n".join(part for part in (stdout, stderr) if part)
        polarity = "negative" if self._is_negative(exit_code, combined) else "positive"

        excerpt_parts = [f"test: {command}"] if command else []
        excerpt_parts.extend(part for part in (stdout, stderr) if part)
        if exit_code is not None:
            excerpt_parts.append(f"exit_code: {exit_code}")

        return [
            make_evidence(
                envelope,
                kind="test_output",
                source_tool="Test",
                scope_kind="test",
                scope_ref=command or envelope.tool_use_id,
                polarity=polarity,
                excerpt=clip_excerpt("\n".join(excerpt_parts).strip()),
                metadata={
                    "tool_use_id": envelope.tool_use_id,
                    "command": command,
                    "exit_code": exit_code,
                },
            )
        ]

    def changed_files(self, envelope) -> list[str]:
        return []

    @staticmethod
    def _is_negative(exit_code, combined: str) -> bool:
        if isinstance(exit_code, int) and exit_code != 0:
            return True
        return any(pattern.search(combined) for pattern in _FAILURE_PATTERNS)

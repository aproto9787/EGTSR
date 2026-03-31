from __future__ import annotations

import re
import shlex

from egtsr_runtime.ingest.excerpt import clip_excerpt
from egtsr_runtime.ingest.normalizer import as_text, get_tool_input, get_tool_response, make_evidence

_NEGATIVE_PATTERNS = (
    re.compile(r"\bFAIL(?:ED|URES?)?\b", re.IGNORECASE),
    re.compile(r"\bERROR\b", re.IGNORECASE),
    re.compile(r"Traceback", re.IGNORECASE),
    re.compile(r"\bException\b", re.IGNORECASE),
)


class BashNormalizer:
    def normalize(self, envelope) -> list:
        """Create evidence from Bash tool result."""
        tool_input = get_tool_input(envelope)
        tool_response = get_tool_response(envelope)
        command = as_text(tool_input.get("command")).strip()
        stdout = as_text(tool_response.get("stdout")).strip()
        stderr = as_text(tool_response.get("stderr")).strip()
        exit_code = tool_response.get("exit_code")
        merged_output = "\n".join(part for part in (stdout, stderr) if part)
        polarity = "negative" if self._is_negative(exit_code, merged_output) else "positive"

        excerpt_parts = [f"command: {command}"] if command else []
        if stdout:
            excerpt_parts.append(stdout)
        if stderr:
            excerpt_parts.append(stderr)
        if exit_code is not None:
            excerpt_parts.append(f"exit_code: {exit_code}")

        return [
            make_evidence(
                envelope,
                kind="bash_output",
                source_tool="Bash",
                scope_kind="command",
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
        """Extract changed files from bash commands when it is obvious."""
        tool_input = get_tool_input(envelope)
        tool_response = get_tool_response(envelope)
        command = as_text(tool_input.get("command")).strip()
        stdout = as_text(tool_response.get("stdout")).strip()
        if not command:
            return []

        if "git diff --name-only" in command:
            return _dedupe(_split_output_paths(stdout))
        if "git status --porcelain" in command:
            return _dedupe(_parse_git_status(stdout))

        matches: list[str] = []
        for pattern in (
            r"(?:^|[;&|]\s*)touch\s+([^\s;&|]+)",
            r">>\s*([^\s;&|]+)",
            r">\s*([^\s;&|]+)",
            r"(?:^|[;&|]\s*)tee\s+([^\s;&|]+)",
            r"(?:^|[;&|]\s*)sed\s+-i(?:\S*)?\s+([^\s;&|]+)",
        ):
            matches.extend(re.findall(pattern, command))

        parsed = _parse_simple_command(command)
        if parsed:
            verb, *rest = parsed
            if verb in {"cp", "mv", "install"} and rest:
                matches.append(rest[-1])
            elif verb == "rm" and rest:
                matches.extend(arg for arg in rest if not arg.startswith("-"))

        return _dedupe(_strip_quotes(item) for item in matches if item)

    @staticmethod
    def _is_negative(exit_code, merged_output: str) -> bool:
        if isinstance(exit_code, int) and exit_code != 0:
            return True
        return any(pattern.search(merged_output) for pattern in _NEGATIVE_PATTERNS)


def _parse_simple_command(command: str) -> list[str]:
    try:
        return shlex.split(command)
    except ValueError:
        return []


def _split_output_paths(stdout: str) -> list[str]:
    return [line.strip() for line in stdout.splitlines() if line.strip()]


def _parse_git_status(stdout: str) -> list[str]:
    paths: list[str] = []
    for line in stdout.splitlines():
        stripped = line.strip()
        if len(stripped) >= 4:
            paths.append(stripped[3:].strip())
    return paths


def _strip_quotes(text: str) -> str:
    return text.strip().strip("\"'")


def _dedupe(items) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result

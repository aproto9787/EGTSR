"""External contract validation.

Provides assertions that verify hook stdout JSON, snapshot files,
and MCP response structures match their frozen contracts.
These are used in tests and by the shadow runner.
"""
from __future__ import annotations


# ── Hook response contract ───────────────────────────────────────────

# Claude Code only validates hookSpecificOutput for these hook types.
_HOOKS_WITH_SPECIFIC_OUTPUT = frozenset({"UserPromptSubmit", "PostToolUse", "PreToolUse"})
_ALLOW_REQUIRED_KEYS = {"hookSpecificOutput"}
_BLOCK_REQUIRED_KEYS = {"decision", "reason", "hookSpecificOutput"}
_HOOK_SPECIFIC_REQUIRED = {"additionalContext"}

# Top-level keys allowed by the Claude Code hook output schema.
_VALID_TOP_LEVEL_KEYS = frozenset({
    "continue", "suppressOutput", "stopReason",
    "decision", "reason", "systemMessage", "hookSpecificOutput",
})


def validate_hook_response(response: dict, hook_event_name: str | None = None) -> list[str]:
    """Validate a hook response dict against the frozen contract.

    Args:
        response: The hook response dict.
        hook_event_name: If provided, validates schema rules specific to the
            hook type (e.g. SessionStart/SessionEnd must not include
            hookSpecificOutput).

    Returns a list of violation descriptions (empty = valid).
    """
    violations: list[str] = []
    if not isinstance(response, dict):
        return ["response is not a dict"]

    is_block = response.get("decision") == "block"
    is_session_hook = hook_event_name is not None and hook_event_name not in _HOOKS_WITH_SPECIFIC_OUTPUT

    # Session hooks must NOT include hookSpecificOutput
    if is_session_hook and "hookSpecificOutput" in response:
        violations.append(
            f"hookSpecificOutput not allowed for {hook_event_name}"
        )

    if is_block:
        required = _BLOCK_REQUIRED_KEYS if not is_session_hook else {"decision", "reason"}
        for key in required:
            if key not in response:
                violations.append(f"block response missing key: {key}")
    elif not is_session_hook:
        for key in _ALLOW_REQUIRED_KEYS:
            if key not in response:
                violations.append(f"allow response missing key: {key}")

    hso = response.get("hookSpecificOutput")
    if isinstance(hso, dict):
        for key in _HOOK_SPECIFIC_REQUIRED:
            if key not in hso:
                violations.append(f"hookSpecificOutput missing key: {key}")
    elif hso is not None:
        violations.append("hookSpecificOutput is not a dict")

    return violations


# ── Snapshot file contract ───────────────────────────────────────────

_CAPSULE_REQUIRED_KEYS = {"phase", "header_obligations", "obligation_blocks"}
_RESUME_GATE_REQUIRED_KEYS = {"session_id", "edit_blocked"}


def validate_capsule_snapshot(data: dict) -> list[str]:
    """Validate last_good_decision_capsule.json shape."""
    violations: list[str] = []
    if not isinstance(data, dict):
        return ["capsule snapshot is not a dict"]
    for key in _CAPSULE_REQUIRED_KEYS:
        if key not in data:
            violations.append(f"capsule snapshot missing key: {key}")
    return violations


def validate_resume_gate_snapshot(data: dict) -> list[str]:
    """Validate resume_gate.json shape."""
    violations: list[str] = []
    if not isinstance(data, dict):
        return ["resume gate snapshot is not a dict"]
    for key in _RESUME_GATE_REQUIRED_KEYS:
        if key not in data:
            violations.append(f"resume gate snapshot missing key: {key}")
    return violations

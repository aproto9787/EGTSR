from __future__ import annotations

# Claude Code only supports hookSpecificOutput for these hook event names.
# SessionStart and SessionEnd must NOT include hookSpecificOutput.
_HOOKS_WITH_SPECIFIC_OUTPUT = frozenset({"UserPromptSubmit", "PostToolUse", "PreToolUse"})


def build_allow_response(
    hook_name: str,
    additional_context: str = "",
    system_message: str | None = None,
) -> dict:
    """Build allow/continue JSON response for hook stdout."""
    response: dict = {}

    if hook_name in _HOOKS_WITH_SPECIFIC_OUTPUT:
        response["hookSpecificOutput"] = {
            "hookEventName": hook_name,
            "additionalContext": additional_context,
        }
        if not additional_context:
            response["suppressOutput"] = True
    else:
        # SessionStart / SessionEnd — no hookSpecificOutput allowed.
        # Inject context via systemMessage if provided.
        if additional_context:
            response["systemMessage"] = additional_context
        else:
            response["suppressOutput"] = True

    if system_message is not None:
        response["systemMessage"] = system_message
    return response



def build_block_response(
    reason: str,
    additional_context: str = "",
    system_message: str | None = None,
) -> dict:
    """Build block JSON response for hook stdout."""
    response: dict = {
        "decision": "block",
        "reason": reason,
        "hookSpecificOutput": {
            "additionalContext": additional_context,
        },
    }
    if system_message is not None:
        response["systemMessage"] = system_message
    return response

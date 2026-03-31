from __future__ import annotations


def build_allow_response(
    hook_name: str,
    additional_context: str = "",
    system_message: str | None = None,
) -> dict:
    """Build allow/continue JSON response for hook stdout."""
    response = {
        "hookSpecificOutput": {
            "hookEventName": hook_name,
            "additionalContext": additional_context,
        }
    }
    if system_message is not None:
        response["systemMessage"] = system_message
    if not additional_context:
        response["suppressOutput"] = True
    return response



def build_block_response(
    reason: str,
    additional_context: str = "",
    system_message: str | None = None,
) -> dict:
    """Build block JSON response for hook stdout."""
    response = {
        "decision": "block",
        "reason": reason,
        "hookSpecificOutput": {
            "additionalContext": additional_context,
        },
    }
    if system_message is not None:
        response["systemMessage"] = system_message
    return response

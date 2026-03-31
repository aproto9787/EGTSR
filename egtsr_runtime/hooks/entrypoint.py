"""CLI entrypoint for hook execution.

Usage: python3 -m egtsr_runtime.hooks.entrypoint <hook_name>

Imports are package-absolute so this works from an installed wheel/editable
install without setting PYTHONPATH manually.
"""
from __future__ import annotations

import json
import sys


def main() -> None:
    if len(sys.argv) < 2:
        _fail_open("no hook_name argument")
        return

    hook_name = sys.argv[1]
    raw_text = sys.stdin.read()

    try:
        from egtsr_runtime.hooks.parser import parse_hook_stdin
        envelope = parse_hook_stdin(raw_text)
    except Exception as exc:
        _fail_open(f"parse_error: {exc}")
        return

    try:
        result = _dispatch(hook_name, envelope)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        _fail_open(f"dispatch_error: {exc}")


def _dispatch(hook_name: str, envelope) -> dict:
    from egtsr_runtime.config import RuntimeConfig
    from egtsr_runtime.db.uow import SqliteUnitOfWork
    from egtsr_runtime.hooks.responses import build_allow_response
    from egtsr_runtime.paths import ensure_runtime_dirs

    paths = ensure_runtime_dirs(envelope.cwd)
    config = RuntimeConfig(
        repo_root=envelope.cwd,
        egtsr_dir=paths.egtsr_dir,
        db_path=paths.db_path,
    )

    with SqliteUnitOfWork(paths) as uow:
        if hook_name == "session_start":
            from egtsr_runtime.hooks.session_start import SessionBootstrapService
            result = SessionBootstrapService(uow, paths.raw_events_dir).load_or_create(envelope)
            return build_allow_response(
                envelope.hook_event_name,
                additional_context=result.additional_context or "",
            )

        elif hook_name == "user_prompt_submit":
            from egtsr_runtime.hooks.user_prompt_submit import UserPromptSubmitService
            result = UserPromptSubmitService(uow, config, paths.raw_events_dir).handle(envelope)
            return result.response

        elif hook_name == "post_tool_use":
            from egtsr_runtime.hooks.post_tool_use import PostToolUseService
            PostToolUseService(uow, paths.raw_events_dir).handle(envelope)
            return build_allow_response(envelope.hook_event_name)

        elif hook_name == "session_end":
            from egtsr_runtime.hooks.session_end import SessionEndService
            return SessionEndService(uow, paths, paths.raw_events_dir).handle(envelope)

        else:
            return build_allow_response(envelope.hook_event_name)


def _fail_open(reason: str) -> None:
    """Output fail-open response and exit 0 so Claude Code continues."""
    response = {
        "hookSpecificOutput": {
            "additionalContext": f"egtsr_entrypoint_fail_open: {reason}",
        },
        "suppressOutput": False,
    }
    print(json.dumps(response, ensure_ascii=False))


if __name__ == "__main__":
    main()

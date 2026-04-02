"""CLI entrypoint for hook execution.

Usage: python3 -m egtsr_runtime.hooks.entrypoint <hook_name>

When daemon mode is enabled, the entrypoint acts as a thin client:
it forwards the request to the resident daemon and prints the response.
If the daemon is unavailable, it falls back to the legacy inline path.
"""
from __future__ import annotations

import json
import os
import sys


def main() -> None:
    if len(sys.argv) < 2:
        _fail_response("unknown", "no hook_name argument")
        return

    hook_name = sys.argv[1]
    raw_text = sys.stdin.read()

    # Fast path: try daemon mode
    daemon_result = _try_daemon(hook_name, raw_text)
    if daemon_result is not None:
        print(json.dumps(daemon_result, ensure_ascii=False))
        return

    # Legacy inline path
    try:
        from egtsr_runtime.hooks.parser import parse_hook_stdin

        envelope = parse_hook_stdin(raw_text)
    except Exception as exc:
        _fail_response(hook_name, f"parse_error: {exc}")
        return

    try:
        from egtsr_runtime.hooks.timer import timed_hook

        result, _timing = timed_hook(hook_name, lambda: _dispatch(hook_name, envelope))
        print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        _fail_response(hook_name, f"dispatch_error: {exc}")


def _try_daemon(hook_name: str, raw_text: str) -> dict | None:
    """Attempt to dispatch via the resident daemon.

    Returns the hook response dict on success, or ``None`` to fall back
    to the legacy inline path.  Any exception triggers fallback.
    """
    try:
        payload = json.loads(raw_text)
        cwd = payload.get("cwd")
        if not isinstance(cwd, str) or not cwd:
            return None

        from egtsr_runtime.hooks.parser import normalize_hook_cwd
        from egtsr_runtime.runtime_locator import resolve_project_dir

        cwd = normalize_hook_cwd(cwd, payload.get("transcript_path"))
        egtsr_dir = str(resolve_project_dir(cwd))

        if not _is_daemon_enabled(egtsr_dir):
            return None

        from egtsr_runtime.daemon.client import try_daemon_hook

        return try_daemon_hook(
            hook_name=hook_name,
            raw_stdin=raw_text,
            egtsr_dir=egtsr_dir,
            repo_root=cwd,
        )
    except Exception:
        return None


def _is_daemon_enabled(egtsr_dir: str) -> bool:
    """Check the ``enable_daemon`` flag with minimal imports."""
    env_val = os.environ.get("EGTSR_ENABLE_DAEMON")
    if env_val is not None:
        return env_val.lower() in ("1", "true", "yes", "on")

    flags_path = os.path.join(egtsr_dir, "runtime_flags.json")
    try:
        with open(flags_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        val = data.get("enable_daemon")
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() in ("1", "true", "yes", "on")
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return False


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

    # Step 07: apply overrides (incl. mode matrix) for all hooks
    from egtsr_runtime.config import apply_overrides

    config = apply_overrides(config)

    with SqliteUnitOfWork(paths) as uow:
        if hook_name == "session_start":
            from egtsr_runtime.hooks.session_start import SessionBootstrapService

            result = SessionBootstrapService(uow, paths.raw_events_dir).load_or_create(
                envelope
            )
            return build_allow_response(
                envelope.hook_event_name,
                additional_context=result.additional_context or "",
            )

        elif hook_name == "user_prompt_submit":
            from egtsr_runtime.hooks.user_prompt_submit import UserPromptSubmitService

            result = UserPromptSubmitService(
                uow, config, paths.raw_events_dir
            ).handle(envelope)
            return result.response

        elif hook_name == "post_tool_use":
            from egtsr_runtime.hooks.post_tool_use import PostToolUseService

            PostToolUseService(uow, paths.raw_events_dir, config).handle(envelope)
            return build_allow_response(envelope.hook_event_name)

        elif hook_name == "session_end":
            from egtsr_runtime.hooks.session_end import SessionEndService

            return SessionEndService(uow, paths, paths.raw_events_dir).handle(envelope)

        else:
            return build_allow_response(envelope.hook_event_name)


def _fail_response(hook_name: str, reason: str) -> None:
    """Output fail-closed (block) for user_prompt_submit, fail-open (allow) for others.

    user_prompt_submit is the safety-critical gate: any exception must block
    to prevent unvetted prompts from passing through.  All other hooks may
    fall back to allow so Claude Code is not entirely stalled.

    Note: hookSpecificOutput is only valid for UserPromptSubmit, PostToolUse,
    PreToolUse.  Session hooks (session_start, session_end) must not include it.
    """
    if hook_name == "user_prompt_submit":
        response = {
            "decision": "block",
            "reason": f"egtsr_fail_closed: {reason}",
            "hookSpecificOutput": {
                "additionalContext": f"egtsr_fail_closed: {reason}",
            },
        }
    elif hook_name in ("session_start", "session_end"):
        # Session hooks: no hookSpecificOutput — use top-level fields only
        response: dict = {}
    elif hook_name == "post_tool_use":
        response = {
            "hookSpecificOutput": {
                "hookEventName": "PostToolUse",
                "additionalContext": f"egtsr_entrypoint_fail_open: {reason}",
            },
            "suppressOutput": False,
        }
    else:
        response = {}
    print(json.dumps(response, ensure_ascii=False))


if __name__ == "__main__":
    main()

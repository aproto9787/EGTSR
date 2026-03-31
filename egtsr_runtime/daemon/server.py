"""Resident hook daemon server.

Boots once, holds DB connection and runtime state, then processes hook
requests sequentially over a Unix domain socket.
"""
from __future__ import annotations

import os
import signal
import socket
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from egtsr_runtime.config import RuntimeConfig, apply_overrides
from egtsr_runtime.daemon.protocol import (
    PROTOCOL_VERSION,
    DaemonResponse,
    recv_message,
    send_message,
)
from egtsr_runtime.daemon.registry import (
    DaemonControlInfo,
    cleanup_stale,
    control_dir,
    remove_control,
    socket_path,
    write_control,
)
from egtsr_runtime.db.runtime import SqliteRuntime
from egtsr_runtime.hooks.parser import parse_hook_stdin
from egtsr_runtime.hooks.responses import build_allow_response
from egtsr_runtime.hooks.timer import timed_hook
from egtsr_runtime.paths import RuntimePaths, ensure_runtime_dirs

DEFAULT_IDLE_TIMEOUT = 300  # seconds


class DaemonServer:
    """Single-threaded resident daemon for EGTSR hook dispatch."""

    def __init__(self, repo_root: str, idle_timeout: int = DEFAULT_IDLE_TIMEOUT):
        self.repo_root = str(Path(repo_root).expanduser().resolve())
        self.idle_timeout = idle_timeout
        self._paths: RuntimePaths | None = None
        self._config: RuntimeConfig | None = None
        self._runtime: SqliteRuntime | None = None
        self._conn: Any = None  # sqlite3.Connection
        self._sock: socket.socket | None = None
        self._running = False
        self._last_activity = 0.0

    # -- lifecycle ---------------------------------------------------------

    def boot(self) -> None:
        """One-time bootstrap: dirs, config, DB, migrations, socket, control file."""
        self._paths = ensure_runtime_dirs(self.repo_root)
        self._config = RuntimeConfig(
            repo_root=self.repo_root,
            egtsr_dir=self._paths.egtsr_dir,
            db_path=self._paths.db_path,
        )
        apply_overrides(self._config)

        # Persistent DB connection — opened once, reused across requests.
        self._runtime = SqliteRuntime(self._paths.db_path)
        self._conn = self._runtime.boot()

        # Clean up any stale control/socket from a dead daemon
        cleanup_stale(self._paths.egtsr_dir)

        # Bind Unix socket
        sock_path = socket_path(self._paths.egtsr_dir)
        control_dir(self._paths.egtsr_dir).mkdir(parents=True, exist_ok=True)
        try:
            Path(sock_path).unlink(missing_ok=True)
        except OSError:
            pass

        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(sock_path)
        self._sock.listen(1)
        self._sock.settimeout(1.0)  # poll interval for idle check

        # Write control file so clients can discover us
        now = datetime.now(timezone.utc).isoformat()
        write_control(
            self._paths.egtsr_dir,
            DaemonControlInfo(
                protocol_version=PROTOCOL_VERSION,
                repo_root=self.repo_root,
                pid=os.getpid(),
                transport="unix_socket",
                socket_path=sock_path,
                port=None,
                started_at=now,
                last_seen_at=now,
            ),
        )

    def serve(self) -> None:
        """Run sequential request loop until idle timeout or shutdown signal."""
        self._running = True
        self._last_activity = time.monotonic()

        # Signal handlers can only be set in the main thread
        signals_set = False
        try:
            prev_term = signal.getsignal(signal.SIGTERM)
            prev_int = signal.getsignal(signal.SIGINT)
            signal.signal(signal.SIGTERM, self._signal_handler)
            signal.signal(signal.SIGINT, self._signal_handler)
            signals_set = True
        except ValueError:
            pass  # not in main thread (e.g. tests)

        try:
            while self._running:
                if time.monotonic() - self._last_activity > self.idle_timeout:
                    break
                try:
                    client, _ = self._sock.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                try:
                    self._handle_client(client)
                finally:
                    client.close()
        finally:
            if signals_set:
                signal.signal(signal.SIGTERM, prev_term)
                signal.signal(signal.SIGINT, prev_int)
            self._shutdown()

    # -- request handling --------------------------------------------------

    def _handle_client(self, client: socket.socket) -> None:
        """Handle a single client connection (one request, one response)."""
        client.settimeout(5.0)
        try:
            msg = recv_message(client)
        except (OSError, socket.timeout):
            return
        if msg is None:
            return

        self._last_activity = time.monotonic()
        request_id = msg.get("request_id", "")
        msg_type = msg.get("type", "hook")

        if msg_type == "ping":
            send_message(client, DaemonResponse.pong(request_id, os.getpid()))
            return

        if msg_type == "shutdown":
            send_message(client, DaemonResponse.success(request_id))
            self._running = False
            return

        if msg_type == "hook":
            resp = self._dispatch_hook(msg)
            send_message(client, resp)
            return

        send_message(
            client,
            DaemonResponse.failure(request_id, f"unknown request type: {msg_type}"),
        )

    def _dispatch_hook(self, msg: dict) -> DaemonResponse:
        """Parse raw stdin and dispatch to the appropriate hook handler."""
        request_id = msg.get("request_id", "")
        hook_name = msg.get("hook_name")
        raw_stdin = msg.get("raw_stdin", "")

        if not hook_name:
            return DaemonResponse.failure(request_id, "missing hook_name")

        try:
            envelope = parse_hook_stdin(raw_stdin)
        except Exception as exc:
            return DaemonResponse.failure(request_id, f"parse_error: {exc}")

        try:
            result, _ = timed_hook(
                hook_name,
                lambda: self._run_hook(hook_name, envelope),
            )
            return DaemonResponse.success(
                request_id,
                hook_response=result,
                diagnostics={"mode": "daemon", "server_pid": os.getpid()},
            )
        except Exception as exc:
            return DaemonResponse.failure(request_id, f"dispatch_error: {exc}")

    def _run_hook(self, hook_name: str, envelope: Any) -> dict:
        """Execute hook handler on the persistent DB connection."""
        from egtsr_runtime.db.uow import SqliteUnitOfWork

        uow = SqliteUnitOfWork(self._conn)
        with uow:
            try:
                return self._call_handler(hook_name, envelope, uow)
            except Exception:
                if self._conn and self._conn.in_transaction:
                    self._conn.rollback()
                raise

    def _call_handler(self, hook_name: str, envelope: Any, uow: Any) -> dict:
        """Dispatch to the same handler services used by the legacy path."""
        if hook_name == "session_start":
            from egtsr_runtime.hooks.session_start import SessionBootstrapService

            result = SessionBootstrapService(
                uow, self._paths.raw_events_dir
            ).load_or_create(envelope)
            return build_allow_response(
                envelope.hook_event_name,
                additional_context=result.additional_context or "",
            )

        if hook_name == "user_prompt_submit":
            from egtsr_runtime.hooks.user_prompt_submit import UserPromptSubmitService

            result = UserPromptSubmitService(
                uow, self._config, self._paths.raw_events_dir
            ).handle(envelope)
            return result.response

        if hook_name == "post_tool_use":
            from egtsr_runtime.hooks.post_tool_use import PostToolUseService

            PostToolUseService(uow, self._paths.raw_events_dir, self._config).handle(envelope)
            return build_allow_response(envelope.hook_event_name)

        if hook_name == "session_end":
            from egtsr_runtime.hooks.session_end import SessionEndService

            return SessionEndService(
                uow, self._paths, self._paths.raw_events_dir
            ).handle(envelope)

        return build_allow_response(envelope.hook_event_name)

    # -- internal ----------------------------------------------------------

    def _signal_handler(self, signum: int, frame: Any) -> None:
        self._running = False

    def _shutdown(self) -> None:
        """Clean up socket, DB connection, control file."""
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

        if self._runtime is not None:
            self._runtime.shutdown()
            self._runtime = None
            self._conn = None

        if self._paths is not None:
            remove_control(self._paths.egtsr_dir)
            sp = socket_path(self._paths.egtsr_dir)
            try:
                Path(sp).unlink(missing_ok=True)
            except OSError:
                pass


def run_daemon(repo_root: str, idle_timeout: int = DEFAULT_IDLE_TIMEOUT) -> None:
    """Entry point for starting the daemon process."""
    server = DaemonServer(repo_root, idle_timeout)
    server.boot()
    server.serve()

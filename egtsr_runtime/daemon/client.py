"""Thin daemon client — connect, forward, print.

If the daemon is not running, the client tries to spawn it.
If all attempts fail, returns ``None`` to signal legacy fallback.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time

from egtsr_runtime.daemon.protocol import (
    DaemonRequest,
    recv_message,
    send_message,
)
from egtsr_runtime.daemon.registry import (
    DaemonControlInfo,
    cleanup_stale,
    is_pid_alive,
    read_control,
)

PING_TIMEOUT = 0.3  # seconds
HOOK_TIMEOUT = 10.0  # seconds
SPAWN_RETRIES = 5
SPAWN_WAIT_BASE = 0.15  # seconds, multiplied by attempt number


def try_daemon_hook(
    hook_name: str,
    raw_stdin: str,
    egtsr_dir: str,
    repo_root: str,
) -> dict | None:
    """Dispatch *hook_name* via the resident daemon.

    Returns the ``hook_response`` dict on success or ``None`` if the daemon
    is unavailable (caller should fall back to the legacy path).
    """
    info = _ensure_daemon(egtsr_dir, repo_root)
    if info is None:
        return None
    return _send_hook(info, hook_name, raw_stdin, repo_root)


def send_ping(egtsr_dir: str) -> bool:
    """Send a health-check ping. Returns ``True`` if the daemon responds."""
    info = read_control(egtsr_dir)
    if info is None:
        return False
    return _ping(info)


def send_shutdown(egtsr_dir: str) -> bool:
    """Ask the daemon to shut down gracefully. Returns ``True`` on success."""
    info = read_control(egtsr_dir)
    if info is None:
        return False
    try:
        sock = _connect(info)
        if sock is None:
            return False
        try:
            send_message(sock, DaemonRequest.shutdown())
            resp = recv_message(sock)
            return resp is not None and resp.get("ok") is True
        finally:
            sock.close()
    except Exception:
        return False


# -- internal --------------------------------------------------------------


def _ensure_daemon(egtsr_dir: str, repo_root: str) -> DaemonControlInfo | None:
    """Make sure the daemon is running. Returns control info or ``None``."""
    info = read_control(egtsr_dir)
    if info is not None:
        if is_pid_alive(info.pid) and _ping(info):
            return info
        # Stale or unresponsive — clean up and respawn
        cleanup_stale(egtsr_dir)

    return _spawn_daemon(repo_root, egtsr_dir)


def _ping(info: DaemonControlInfo) -> bool:
    """Send ping to daemon and verify response."""
    try:
        sock = _connect(info, timeout=PING_TIMEOUT)
        if sock is None:
            return False
        try:
            send_message(sock, DaemonRequest.ping())
            resp = recv_message(sock)
            return resp is not None and resp.get("ok") is True
        finally:
            sock.close()
    except Exception:
        return False


def _connect(
    info: DaemonControlInfo,
    timeout: float = PING_TIMEOUT,
) -> socket.socket | None:
    """Connect to the daemon via the transport specified in control info."""
    try:
        if info.transport == "unix_socket" and info.socket_path:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect(info.socket_path)
            return s
        if info.transport == "tcp" and info.port:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            s.connect(("127.0.0.1", info.port))
            return s
    except (OSError, socket.timeout):
        pass
    return None


def _spawn_daemon(repo_root: str, egtsr_dir: str) -> DaemonControlInfo | None:
    """Spawn daemon subprocess and poll until it is ready."""
    try:
        subprocess.Popen(
            [sys.executable, "-m", "egtsr_runtime.daemon", repo_root],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception:
        return None

    for attempt in range(SPAWN_RETRIES):
        time.sleep(SPAWN_WAIT_BASE * (attempt + 1))
        info = read_control(egtsr_dir)
        if info is not None and is_pid_alive(info.pid) and _ping(info):
            return info
    return None


def _send_hook(
    info: DaemonControlInfo,
    hook_name: str,
    raw_stdin: str,
    repo_root: str,
) -> dict | None:
    """Send hook request to daemon and return ``hook_response``."""
    try:
        sock = _connect(info, timeout=HOOK_TIMEOUT)
        if sock is None:
            return None
        try:
            request = DaemonRequest.hook(
                hook_name=hook_name,
                cwd=repo_root,
                session_id="",
                raw_stdin=raw_stdin,
            )
            send_message(sock, request)
            resp = recv_message(sock)
            if resp is not None and resp.get("ok") is True:
                return resp.get("hook_response")
        finally:
            sock.close()
    except Exception:
        pass
    return None

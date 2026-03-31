"""Daemon control file (registry) management.

Control state is stored at ``.egtsr/daemon/control.json``.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(slots=True)
class DaemonControlInfo:
    protocol_version: str
    repo_root: str
    pid: int
    transport: str  # "unix_socket" or "tcp"
    socket_path: str | None
    port: int | None
    started_at: str
    last_seen_at: str


def control_dir(egtsr_dir: str) -> Path:
    """Return the daemon subdirectory path."""
    return Path(egtsr_dir) / "daemon"


def control_file_path(egtsr_dir: str) -> Path:
    """Return the path to the daemon control file."""
    return control_dir(egtsr_dir) / "control.json"


def socket_path(egtsr_dir: str) -> str:
    """Return the default Unix socket path for this egtsr dir."""
    return str(control_dir(egtsr_dir) / "egtsr.sock")


def write_control(egtsr_dir: str, info: DaemonControlInfo) -> None:
    """Write the daemon control file atomically."""
    d = control_dir(egtsr_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / "control.json"
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(asdict(info), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(path)


def read_control(egtsr_dir: str) -> DaemonControlInfo | None:
    """Read the daemon control file. Returns ``None`` if absent or corrupt."""
    path = control_file_path(egtsr_dir)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return DaemonControlInfo(
            protocol_version=str(data["protocol_version"]),
            repo_root=str(data["repo_root"]),
            pid=int(data["pid"]),
            transport=str(data["transport"]),
            socket_path=data.get("socket_path"),
            port=data.get("port"),
            started_at=str(data["started_at"]),
            last_seen_at=str(data.get("last_seen_at", data["started_at"])),
        )
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def remove_control(egtsr_dir: str) -> None:
    """Remove the daemon control file if it exists."""
    try:
        control_file_path(egtsr_dir).unlink(missing_ok=True)
    except OSError:
        pass


def is_pid_alive(pid: int) -> bool:
    """Check whether a process with *pid* exists."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False


def cleanup_stale(egtsr_dir: str) -> bool:
    """Remove control file and socket if the daemon PID is dead.

    Returns ``True`` when a stale entry was cleaned up.
    """
    info = read_control(egtsr_dir)
    if info is None:
        return False
    if not is_pid_alive(info.pid):
        remove_control(egtsr_dir)
        if info.socket_path:
            try:
                Path(info.socket_path).unlink(missing_ok=True)
            except OSError:
                pass
        return True
    return False

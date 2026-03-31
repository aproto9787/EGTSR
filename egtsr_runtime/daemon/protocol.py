"""Daemon request/response protocol.

Wire format: 4-byte big-endian length prefix followed by UTF-8 JSON payload.
"""
from __future__ import annotations

import json
import struct
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal

PROTOCOL_VERSION = "1"
_HEADER_SIZE = 4  # uint32 big-endian

RequestType = Literal["hook", "ping", "shutdown"]


@dataclass(slots=True)
class DaemonRequest:
    protocol_version: str
    request_id: str
    type: RequestType
    hook_name: str | None = None
    cwd: str | None = None
    session_id: str | None = None
    raw_stdin: str | None = None
    received_at: str | None = None

    @classmethod
    def hook(
        cls,
        hook_name: str,
        cwd: str,
        session_id: str,
        raw_stdin: str,
    ) -> DaemonRequest:
        return cls(
            protocol_version=PROTOCOL_VERSION,
            request_id=uuid.uuid4().hex,
            type="hook",
            hook_name=hook_name,
            cwd=cwd,
            session_id=session_id,
            raw_stdin=raw_stdin,
            received_at=datetime.now(timezone.utc).isoformat(),
        )

    @classmethod
    def ping(cls) -> DaemonRequest:
        return cls(
            protocol_version=PROTOCOL_VERSION,
            request_id=uuid.uuid4().hex,
            type="ping",
        )

    @classmethod
    def shutdown(cls) -> DaemonRequest:
        return cls(
            protocol_version=PROTOCOL_VERSION,
            request_id=uuid.uuid4().hex,
            type="shutdown",
        )


@dataclass(slots=True)
class DaemonResponse:
    protocol_version: str
    request_id: str
    ok: bool
    hook_response: dict[str, Any] | None = None
    error: str | None = None
    diagnostics: dict[str, Any] | None = None

    @classmethod
    def success(
        cls,
        request_id: str,
        hook_response: dict[str, Any] | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> DaemonResponse:
        return cls(
            protocol_version=PROTOCOL_VERSION,
            request_id=request_id,
            ok=True,
            hook_response=hook_response,
            diagnostics=diagnostics,
        )

    @classmethod
    def failure(cls, request_id: str, error: str) -> DaemonResponse:
        return cls(
            protocol_version=PROTOCOL_VERSION,
            request_id=request_id,
            ok=False,
            error=error,
        )

    @classmethod
    def pong(cls, request_id: str, pid: int) -> DaemonResponse:
        return cls(
            protocol_version=PROTOCOL_VERSION,
            request_id=request_id,
            ok=True,
            diagnostics={"type": "pong", "pid": pid},
        )


def send_message(sock, msg: DaemonRequest | DaemonResponse) -> None:
    """Send a length-prefixed JSON message on *sock*."""
    payload = json.dumps(asdict(msg), ensure_ascii=False).encode("utf-8")
    sock.sendall(struct.pack("!I", len(payload)) + payload)


def recv_message(sock) -> dict[str, Any] | None:
    """Read one length-prefixed JSON message from *sock*. Returns ``None`` on EOF."""
    header = _recv_exact(sock, _HEADER_SIZE)
    if header is None:
        return None
    (length,) = struct.unpack("!I", header)
    if length == 0:
        return None
    payload = _recv_exact(sock, length)
    if payload is None:
        return None
    return json.loads(payload.decode("utf-8"))


def _recv_exact(sock, n: int) -> bytes | None:
    """Read exactly *n* bytes from *sock*, or ``None`` on premature EOF."""
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)

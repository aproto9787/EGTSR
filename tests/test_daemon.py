"""Tests for the resident hook daemon (Step 01)."""
from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path

from egtsr_runtime.daemon.protocol import (
    DaemonRequest,
    DaemonResponse,
    recv_message,
    send_message,
)
from egtsr_runtime.daemon.registry import (
    DaemonControlInfo,
    cleanup_stale,
    is_pid_alive,
    read_control,
    remove_control,
    socket_path,
    write_control,
)


# ---------------------------------------------------------------------------
# Protocol tests
# ---------------------------------------------------------------------------

class TestProtocol(unittest.TestCase):
    """Verify length-prefixed JSON encode/decode via socketpair."""

    def test_ping_roundtrip(self):
        a, b = socket.socketpair()
        try:
            send_message(a, DaemonRequest.ping())
            msg = recv_message(b)
            self.assertIsNotNone(msg)
            self.assertEqual(msg["type"], "ping")
            self.assertEqual(msg["protocol_version"], "1")
        finally:
            a.close()
            b.close()

    def test_pong_roundtrip(self):
        a, b = socket.socketpair()
        try:
            send_message(a, DaemonResponse.pong("req-1", 42))
            msg = recv_message(b)
            self.assertIsNotNone(msg)
            self.assertTrue(msg["ok"])
            self.assertEqual(msg["diagnostics"]["pid"], 42)
        finally:
            a.close()
            b.close()

    def test_hook_request_roundtrip(self):
        a, b = socket.socketpair()
        try:
            payload = '{"hook_event_name":"SessionStart","session_id":"s1","cwd":"/tmp"}'
            send_message(a, DaemonRequest.hook("session_start", "/tmp", "s1", payload))
            msg = recv_message(b)
            self.assertEqual(msg["type"], "hook")
            self.assertEqual(msg["hook_name"], "session_start")
            self.assertEqual(msg["raw_stdin"], payload)
        finally:
            a.close()
            b.close()

    def test_failure_response(self):
        a, b = socket.socketpair()
        try:
            send_message(a, DaemonResponse.failure("req-2", "something broke"))
            msg = recv_message(b)
            self.assertFalse(msg["ok"])
            self.assertEqual(msg["error"], "something broke")
        finally:
            a.close()
            b.close()

    def test_eof_returns_none(self):
        a, b = socket.socketpair()
        a.close()
        self.assertIsNone(recv_message(b))
        b.close()

    def test_shutdown_request(self):
        a, b = socket.socketpair()
        try:
            send_message(a, DaemonRequest.shutdown())
            msg = recv_message(b)
            self.assertEqual(msg["type"], "shutdown")
        finally:
            a.close()
            b.close()


# ---------------------------------------------------------------------------
# Registry tests
# ---------------------------------------------------------------------------

class TestRegistry(unittest.TestCase):
    """Control file CRUD and stale cleanup."""

    def _make_info(self, tmp: str, pid: int | None = None) -> DaemonControlInfo:
        return DaemonControlInfo(
            protocol_version="1",
            repo_root=tmp,
            pid=pid or os.getpid(),
            transport="unix_socket",
            socket_path=str(Path(tmp) / ".egtsr" / "daemon" / "egtsr.sock"),
            port=None,
            started_at="2026-01-01T00:00:00Z",
            last_seen_at="2026-01-01T00:00:00Z",
        )

    def test_write_read_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            egtsr_dir = str(Path(tmp) / ".egtsr")
            info = self._make_info(tmp)
            write_control(egtsr_dir, info)

            loaded = read_control(egtsr_dir)
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.pid, os.getpid())
            self.assertEqual(loaded.transport, "unix_socket")
            self.assertEqual(loaded.repo_root, tmp)

    def test_read_missing_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(read_control(str(Path(tmp) / ".egtsr")))

    def test_read_corrupt_returns_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            egtsr_dir = str(Path(tmp) / ".egtsr")
            d = Path(egtsr_dir) / "daemon"
            d.mkdir(parents=True)
            (d / "control.json").write_text("not json", encoding="utf-8")
            self.assertIsNone(read_control(egtsr_dir))

    def test_remove_control(self):
        with tempfile.TemporaryDirectory() as tmp:
            egtsr_dir = str(Path(tmp) / ".egtsr")
            write_control(egtsr_dir, self._make_info(tmp))
            self.assertIsNotNone(read_control(egtsr_dir))
            remove_control(egtsr_dir)
            self.assertIsNone(read_control(egtsr_dir))

    def test_cleanup_stale_dead_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            egtsr_dir = str(Path(tmp) / ".egtsr")
            info = self._make_info(tmp, pid=999999999)
            write_control(egtsr_dir, info)
            self.assertTrue(cleanup_stale(egtsr_dir))
            self.assertIsNone(read_control(egtsr_dir))

    def test_cleanup_stale_alive_pid(self):
        with tempfile.TemporaryDirectory() as tmp:
            egtsr_dir = str(Path(tmp) / ".egtsr")
            write_control(egtsr_dir, self._make_info(tmp))
            self.assertFalse(cleanup_stale(egtsr_dir))
            self.assertIsNotNone(read_control(egtsr_dir))

    def test_is_pid_alive_self(self):
        self.assertTrue(is_pid_alive(os.getpid()))

    def test_is_pid_alive_dead(self):
        self.assertFalse(is_pid_alive(999999999))

    def test_socket_path(self):
        path = socket_path("/tmp/repo/.egtsr")
        self.assertTrue(path.endswith("egtsr.sock"))
        self.assertIn("daemon", path)


# ---------------------------------------------------------------------------
# Daemon server integration tests
# ---------------------------------------------------------------------------

class TestDaemonServer(unittest.TestCase):
    """Start a real daemon in a thread and test roundtrips."""

    @staticmethod
    def _resolve_egtsr_dir(repo_root: str) -> str:
        from egtsr_runtime.runtime_locator import resolve_project_dir

        return str(resolve_project_dir(repo_root))

    def _start_server(self, repo_root: str, idle_timeout: int = 5):
        from egtsr_runtime.daemon.server import DaemonServer

        server = DaemonServer(repo_root, idle_timeout=idle_timeout)
        server.boot()
        t = threading.Thread(target=server.serve, daemon=True)
        t.start()
        # Wait for socket to be ready
        egtsr_dir = self._resolve_egtsr_dir(repo_root)
        for _ in range(20):
            time.sleep(0.05)
            info = read_control(egtsr_dir)
            if info is not None:
                break
        return server, t

    def _connect_to(self, repo_root: str) -> socket.socket:
        egtsr_dir = self._resolve_egtsr_dir(repo_root)
        info = read_control(egtsr_dir)
        self.assertIsNotNone(info, "control file not found")
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(3.0)
        sock.connect(info.socket_path)
        return sock

    def test_ping(self):
        with tempfile.TemporaryDirectory() as tmp:
            server, t = self._start_server(tmp)
            try:
                sock = self._connect_to(tmp)
                send_message(sock, DaemonRequest.ping())
                resp = recv_message(sock)
                sock.close()

                self.assertIsNotNone(resp)
                self.assertTrue(resp["ok"])
                self.assertEqual(resp["diagnostics"]["type"], "pong")
            finally:
                server._running = False
                t.join(timeout=3)

    def test_shutdown_request(self):
        with tempfile.TemporaryDirectory() as tmp:
            server, t = self._start_server(tmp)

            sock = self._connect_to(tmp)
            send_message(sock, DaemonRequest.shutdown())
            resp = recv_message(sock)
            sock.close()

            self.assertTrue(resp["ok"])
            t.join(timeout=3)
            self.assertFalse(t.is_alive())

    def test_hook_session_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            server, t = self._start_server(tmp)
            try:
                hook_payload = json.dumps({
                    "hook_event_name": "SessionStart",
                    "session_id": "test-session-001",
                    "cwd": tmp,
                })

                sock = self._connect_to(tmp)
                send_message(
                    sock,
                    DaemonRequest.hook("session_start", tmp, "test-session-001", hook_payload),
                )
                resp = recv_message(sock)
                sock.close()

                self.assertIsNotNone(resp)
                self.assertTrue(resp["ok"])
                self.assertIn("hook_response", resp)
                hr = resp["hook_response"]
                self.assertIn("hookSpecificOutput", hr)
                self.assertEqual(resp["diagnostics"]["mode"], "daemon")
            finally:
                server._running = False
                t.join(timeout=3)

    def test_hook_post_tool_use(self):
        with tempfile.TemporaryDirectory() as tmp:
            server, t = self._start_server(tmp)
            try:
                # First bootstrap a session
                bootstrap = json.dumps({
                    "hook_event_name": "SessionStart",
                    "session_id": "test-session-002",
                    "cwd": tmp,
                })
                sock = self._connect_to(tmp)
                send_message(sock, DaemonRequest.hook("session_start", tmp, "test-session-002", bootstrap))
                recv_message(sock)
                sock.close()

                # Now send a PostToolUse
                ptu_payload = json.dumps({
                    "hook_event_name": "PostToolUse",
                    "session_id": "test-session-002",
                    "cwd": tmp,
                    "tool_name": "Read",
                    "tool_use_id": "tu-001",
                })
                sock = self._connect_to(tmp)
                send_message(
                    sock,
                    DaemonRequest.hook("post_tool_use", tmp, "test-session-002", ptu_payload),
                )
                resp = recv_message(sock)
                sock.close()

                self.assertTrue(resp["ok"])
                self.assertIn("hookSpecificOutput", resp["hook_response"])
            finally:
                server._running = False
                t.join(timeout=3)

    def test_unknown_request_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            server, t = self._start_server(tmp)
            try:
                sock = self._connect_to(tmp)
                # Manually send an unknown type
                import struct
                msg = json.dumps({
                    "protocol_version": "1",
                    "request_id": "bad-type",
                    "type": "frobnicate",
                }).encode("utf-8")
                sock.sendall(struct.pack("!I", len(msg)) + msg)

                resp = recv_message(sock)
                sock.close()

                self.assertFalse(resp["ok"])
                self.assertIn("unknown", resp["error"])
            finally:
                server._running = False
                t.join(timeout=3)

    def test_invalid_hook_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            server, t = self._start_server(tmp)
            try:
                sock = self._connect_to(tmp)
                send_message(
                    sock,
                    DaemonRequest.hook("session_start", tmp, "", "not valid json!!!"),
                )
                resp = recv_message(sock)
                sock.close()

                self.assertFalse(resp["ok"])
                self.assertIn("parse_error", resp["error"])
            finally:
                server._running = False
                t.join(timeout=3)

    def test_idle_shutdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            server, t = self._start_server(tmp, idle_timeout=1)
            # Don't send any requests — daemon should shut down after 1s idle
            t.join(timeout=5)
            self.assertFalse(t.is_alive())

    def test_multiple_requests_on_same_daemon(self):
        with tempfile.TemporaryDirectory() as tmp:
            server, t = self._start_server(tmp)
            try:
                for i in range(3):
                    sock = self._connect_to(tmp)
                    send_message(sock, DaemonRequest.ping())
                    resp = recv_message(sock)
                    sock.close()
                    self.assertTrue(resp["ok"])
            finally:
                server._running = False
                t.join(timeout=3)

    def test_control_file_cleanup_after_shutdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            server, t = self._start_server(tmp)
            egtsr_dir = self._resolve_egtsr_dir(tmp)

            # Verify control file exists while running
            self.assertIsNotNone(read_control(egtsr_dir))

            # Shutdown
            sock = self._connect_to(tmp)
            send_message(sock, DaemonRequest.shutdown())
            recv_message(sock)
            sock.close()
            t.join(timeout=3)

            # Control file should be cleaned up
            self.assertIsNone(read_control(egtsr_dir))


# ---------------------------------------------------------------------------
# Entrypoint daemon routing tests
# ---------------------------------------------------------------------------

class TestEntrypointDaemonRouting(unittest.TestCase):
    """Test _is_daemon_enabled logic in entrypoint."""

    def test_disabled_by_default(self):
        from egtsr_runtime.hooks.entrypoint import _is_daemon_enabled

        with tempfile.TemporaryDirectory() as tmp:
            egtsr_dir = str(Path(tmp) / ".egtsr")
            Path(egtsr_dir).mkdir()
            self.assertFalse(_is_daemon_enabled(egtsr_dir))

    def test_enabled_via_flags_file(self):
        from egtsr_runtime.hooks.entrypoint import _is_daemon_enabled

        with tempfile.TemporaryDirectory() as tmp:
            egtsr_dir = str(Path(tmp) / ".egtsr")
            Path(egtsr_dir).mkdir()
            (Path(egtsr_dir) / "runtime_flags.json").write_text(
                json.dumps({"enable_daemon": True}), encoding="utf-8"
            )
            self.assertTrue(_is_daemon_enabled(egtsr_dir))

    def test_disabled_via_flags_file(self):
        from egtsr_runtime.hooks.entrypoint import _is_daemon_enabled

        with tempfile.TemporaryDirectory() as tmp:
            egtsr_dir = str(Path(tmp) / ".egtsr")
            Path(egtsr_dir).mkdir()
            (Path(egtsr_dir) / "runtime_flags.json").write_text(
                json.dumps({"enable_daemon": False}), encoding="utf-8"
            )
            self.assertFalse(_is_daemon_enabled(egtsr_dir))

    def test_enabled_via_env(self):
        from egtsr_runtime.hooks.entrypoint import _is_daemon_enabled

        with tempfile.TemporaryDirectory() as tmp:
            egtsr_dir = str(Path(tmp) / ".egtsr")
            Path(egtsr_dir).mkdir()
            old = os.environ.get("EGTSR_ENABLE_DAEMON")
            try:
                os.environ["EGTSR_ENABLE_DAEMON"] = "true"
                self.assertTrue(_is_daemon_enabled(egtsr_dir))
            finally:
                if old is None:
                    os.environ.pop("EGTSR_ENABLE_DAEMON", None)
                else:
                    os.environ["EGTSR_ENABLE_DAEMON"] = old

    def test_env_overrides_file(self):
        from egtsr_runtime.hooks.entrypoint import _is_daemon_enabled

        with tempfile.TemporaryDirectory() as tmp:
            egtsr_dir = str(Path(tmp) / ".egtsr")
            Path(egtsr_dir).mkdir()
            (Path(egtsr_dir) / "runtime_flags.json").write_text(
                json.dumps({"enable_daemon": True}), encoding="utf-8"
            )
            old = os.environ.get("EGTSR_ENABLE_DAEMON")
            try:
                os.environ["EGTSR_ENABLE_DAEMON"] = "false"
                self.assertFalse(_is_daemon_enabled(egtsr_dir))
            finally:
                if old is None:
                    os.environ.pop("EGTSR_ENABLE_DAEMON", None)
                else:
                    os.environ["EGTSR_ENABLE_DAEMON"] = old


# ---------------------------------------------------------------------------
# Client fallback tests
# ---------------------------------------------------------------------------

class TestClientFallback(unittest.TestCase):
    """Verify the client returns None when daemon is unavailable."""

    def test_fallback_when_spawn_fails(self):
        """When spawn is impossible, try_daemon_hook returns None."""
        from egtsr_runtime.daemon import client

        original = client._spawn_daemon
        client._spawn_daemon = lambda *a, **kw: None
        try:
            with tempfile.TemporaryDirectory() as tmp:
                egtsr_dir = str(Path(tmp) / ".egtsr")
                Path(egtsr_dir).mkdir()
                result = client.try_daemon_hook(
                    hook_name="session_start",
                    raw_stdin='{"hook_event_name":"SessionStart","session_id":"s","cwd":"/tmp"}',
                    egtsr_dir=egtsr_dir,
                    repo_root=tmp,
                )
                self.assertIsNone(result)
        finally:
            client._spawn_daemon = original

    def test_send_ping_no_daemon(self):
        from egtsr_runtime.daemon.client import send_ping

        with tempfile.TemporaryDirectory() as tmp:
            egtsr_dir = str(Path(tmp) / ".egtsr")
            Path(egtsr_dir).mkdir()
            self.assertFalse(send_ping(egtsr_dir))

    def test_send_shutdown_no_daemon(self):
        from egtsr_runtime.daemon.client import send_shutdown

        with tempfile.TemporaryDirectory() as tmp:
            egtsr_dir = str(Path(tmp) / ".egtsr")
            Path(egtsr_dir).mkdir()
            self.assertFalse(send_shutdown(egtsr_dir))


if __name__ == "__main__":
    unittest.main()

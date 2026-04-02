from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from egtsr_runtime.config import RuntimeConfig
from egtsr_runtime.db.uow import SqliteUnitOfWork
from egtsr_runtime.enums import InvalidationStatus, ObligationStatus, VerifyPhase
from egtsr_runtime.models import Capsule, InvalidationTicket, Obligation, Session
from egtsr_runtime.paths import ensure_runtime_dirs
from mcp_server.server import EGTSRMCPServer


SESSION_ID = "mcp-server-test-session"


def _make_config(tmp_dir: str) -> RuntimeConfig:
    paths = ensure_runtime_dirs(tmp_dir)
    return RuntimeConfig(repo_root=paths.repo_root, egtsr_dir=paths.egtsr_dir, db_path=paths.db_path)


def _seed_session(uow: SqliteUnitOfWork, session_id: str) -> None:
    uow.sessions.create(
        Session(
            id=session_id,
            repo_root="/tmp/repo",
            branch="main",
            head_hash="abc123",
            status="active",
            created_at="2026-03-31T09:00:00Z",
            updated_at="2026-03-31T09:00:00Z",
        )
    )


def _seed_obligation(uow: SqliteUnitOfWork, session_id: str, obl_id: str, status: ObligationStatus) -> None:
    uow.obligations.upsert(
        Obligation(
            id=obl_id,
            session_id=session_id,
            source="spec",
            statement=f"Obligation {obl_id}",
            priority=50,
            status=status,
            created_at="2026-03-31T09:01:00Z",
            updated_at="2026-03-31T09:01:00Z",
        )
    )


def _seed_ticket(uow: SqliteUnitOfWork, session_id: str, ticket_id: str, status: InvalidationStatus) -> None:
    uow.invalidations.upsert(
        InvalidationTicket(
            id=ticket_id,
            session_id=session_id,
            subject_type="assertion",
            subject_id="as-1",
            trigger_kind="file_change",
            trigger_ref="src/foo.py",
            status=status,
            metadata={},
            created_at="2026-03-31T09:02:00Z",
            updated_at="2026-03-31T09:02:00Z",
        )
    )


def _seed_capsule(uow: SqliteUnitOfWork, session_id: str, cap_id: str, audit_pass: bool = True) -> None:
    uow.capsules.create(
        Capsule(
            id=cap_id,
            session_id=session_id,
            phase=VerifyPhase.DECISION,
            frontier_hash="frontier-abc",
            content="capsule content body",
            token_count=100,
            audit_pass=audit_pass,
            audit_report={"passed": audit_pass},
            created_at="2026-03-31T09:03:00Z",
        )
    )


class TestMCPServer(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.config = _make_config(self.tmp_dir.name)
        self.paths = ensure_runtime_dirs(self.tmp_dir.name)
        Path(self.paths.resume_gate_path).write_text("{}", encoding="utf-8")
        Path(self.paths.last_good_capsule_path).write_text("{}", encoding="utf-8")
        Path(self.paths.log_path).touch()

        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow, SESSION_ID)
            _seed_obligation(uow, SESSION_ID, "obl-1", ObligationStatus.OPEN)
            _seed_obligation(uow, SESSION_ID, "obl-2", ObligationStatus.VERIFIED)
            _seed_ticket(uow, SESSION_ID, "inv-live-1", InvalidationStatus.LIVE)
            _seed_ticket(uow, SESSION_ID, "inv-stale-1", InvalidationStatus.STALE)
            _seed_capsule(uow, SESSION_ID, "cap-1")
            uow.commit()

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    def _make_server(self) -> EGTSRMCPServer:
        return EGTSRMCPServer(db_path=self.config.db_path, project_dir=self.tmp_dir.name)

    @staticmethod
    def _tool_result_payload(response: dict) -> dict:
        return json.loads(response["result"]["content"][0]["text"])

    @staticmethod
    def _frame_request(request: dict) -> bytes:
        body = json.dumps(request, ensure_ascii=False).encode("utf-8")
        return f"Content-Length: {len(body)}\r\n\r\n".encode("utf-8") + body

    @staticmethod
    def _parse_framed_responses(payload: bytes) -> list[tuple[int, dict]]:
        responses: list[tuple[int, dict]] = []
        offset = 0
        while offset < len(payload):
            header_end = payload.find(b"\r\n\r\n", offset)
            if header_end == -1:
                raise AssertionError("Missing header terminator in framed response")
            header = payload[offset:header_end].decode("utf-8")
            if not header.startswith("Content-Length: "):
                raise AssertionError(f"Unexpected header: {header}")
            body_length = int(header.split(": ", 1)[1])
            body_start = header_end + 4
            body_end = body_start + body_length
            body = payload[body_start:body_end]
            responses.append((body_length, json.loads(body.decode("utf-8"))))
            offset = body_end
        return responses

    def _run_server_with_framed_requests(self, payload: bytes) -> bytes:
        server = self._make_server()
        stdin_bytes = io.BytesIO(payload)
        stdout_bytes = io.BytesIO()
        stdin = io.TextIOWrapper(stdin_bytes, encoding="utf-8", newline="")
        stdout = io.TextIOWrapper(stdout_bytes, encoding="utf-8", newline="")
        try:
            server.run(stdin=stdin, stdout=stdout)
            stdout.flush()
            return stdout_bytes.getvalue()
        finally:
            stdin.detach()
            stdout.detach()

    def test_initialize(self) -> None:
        server = self._make_server()
        response = server._handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})

        self.assertEqual(response["result"]["protocolVersion"], "2025-03-26")
        self.assertEqual(response["result"]["serverInfo"]["name"], "egtsr")
        self.assertEqual(response["result"]["serverInfo"]["version"], "0.3.0")
        self.assertIn("tools", response["result"]["capabilities"])

    def test_stdio_response_uses_content_length_framing(self) -> None:
        raw_output = self._run_server_with_framed_requests(
            self._frame_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
        )
        self.assertIn(b"Content-Length: ", raw_output)
        self.assertTrue(raw_output.startswith(b"Content-Length: "))

        responses = self._parse_framed_responses(raw_output)
        self.assertEqual(len(responses), 1)
        body_length, response = responses[0]
        expected_body = json.dumps(response, ensure_ascii=False).encode("utf-8")
        self.assertEqual(body_length, len(expected_body))
        self.assertEqual(response["id"], 1)
        self.assertEqual(response["result"]["serverInfo"]["version"], "0.3.0")

    def test_stdio_response_content_length_matches_json_body_bytes(self) -> None:
        raw_output = self._run_server_with_framed_requests(
            self._frame_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
        )
        header_end = raw_output.index(b"\r\n\r\n")
        header = raw_output[:header_end].decode("utf-8")
        body = raw_output[header_end + 4 :]
        self.assertTrue(header.startswith("Content-Length: "))
        content_length = int(header.split(": ", 1)[1])
        self.assertEqual(content_length, len(body))
        self.assertEqual(content_length, len(body.decode("utf-8").encode("utf-8")))

    def test_stdio_response_framing_survives_multiple_responses(self) -> None:
        raw_output = self._run_server_with_framed_requests(
            self._frame_request({"jsonrpc": "2.0", "id": 10, "method": "initialize", "params": {}})
            + self._frame_request({"jsonrpc": "2.0", "id": 11, "method": "tools/list", "params": {}})
        )
        responses = self._parse_framed_responses(raw_output)
        self.assertEqual(len(responses), 2)
        self.assertEqual([response["id"] for _, response in responses], [10, 11])
        for body_length, response in responses:
            self.assertEqual(body_length, len(json.dumps(response, ensure_ascii=False).encode("utf-8")))

    def test_tools_list(self) -> None:
        server = self._make_server()
        response = server._handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})

        tools = response["result"]["tools"]
        names = {tool["name"] for tool in tools}
        self.assertEqual(len(tools), 6)
        self.assertEqual(
            names,
            {
                "egtsr_inspect_obligations",
                "egtsr_inspect_stale",
                "egtsr_inspect_capsule",
                "egtsr_resume_status",
                "egtsr_doctor",
                "egtsr_session_summary",
            },
        )

    def test_inspect_obligations_call(self) -> None:
        server = self._make_server()
        response = server._handle_request(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "egtsr_inspect_obligations", "arguments": {"session_id": SESSION_ID}},
            }
        )

        payload = self._tool_result_payload(response)
        self.assertEqual(payload["session_id"], SESSION_ID)
        self.assertEqual(payload["total_count"], 2)
        self.assertEqual(payload["open_count"], 1)

    def test_inspect_stale_call(self) -> None:
        server = self._make_server()
        response = server._handle_request(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {"name": "egtsr_inspect_stale", "arguments": {"session_id": SESSION_ID}},
            }
        )

        payload = self._tool_result_payload(response)
        self.assertEqual(payload["live_count"], 1)
        self.assertEqual(payload["stale_count"], 1)

    def test_inspect_capsule_call(self) -> None:
        server = self._make_server()
        response = server._handle_request(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {"name": "egtsr_inspect_capsule", "arguments": {"session_id": SESSION_ID}},
            }
        )

        payload = self._tool_result_payload(response)
        self.assertEqual(payload["capsule_count"], 1)
        self.assertEqual(payload["latest"]["id"], "cap-1")

    def test_resume_status_call(self) -> None:
        server = self._make_server()
        response = server._handle_request(
            {
                "jsonrpc": "2.0",
                "id": 6,
                "method": "tools/call",
                "params": {"name": "egtsr_resume_status", "arguments": {"session_id": SESSION_ID}},
            }
        )

        payload = self._tool_result_payload(response)
        self.assertEqual(payload["session_id"], SESSION_ID)
        self.assertIn("edit_blocked", payload)
        self.assertIn("reason", payload)

    def test_doctor_call(self) -> None:
        server = EGTSRMCPServer(project_dir=self.tmp_dir.name)
        response = server._handle_request(
            {
                "jsonrpc": "2.0",
                "id": 7,
                "method": "tools/call",
                "params": {"name": "egtsr_doctor", "arguments": {"project_dir": self.tmp_dir.name}},
            }
        )

        payload = self._tool_result_payload(response)
        self.assertTrue(payload["db_ok"])
        self.assertTrue(payload["gate_ok"])
        self.assertTrue(payload["capsule_ok"])
        self.assertTrue(payload["dirs_ok"])
        self.assertTrue(payload["log_ok"])
        self.assertTrue(payload["overall"])

    def test_session_summary_call(self) -> None:
        server = self._make_server()
        response = server._handle_request(
            {
                "jsonrpc": "2.0",
                "id": 8,
                "method": "tools/call",
                "params": {"name": "egtsr_session_summary", "arguments": {"session_id": SESSION_ID}},
            }
        )

        payload = self._tool_result_payload(response)
        self.assertEqual(payload["obligations"]["total_count"], 2)
        self.assertEqual(payload["stale"]["live_count"], 1)
        self.assertEqual(payload["capsule"]["capsule_count"], 1)
        self.assertEqual(payload["resume"]["session_id"], SESSION_ID)

    def test_invalid_session_id(self) -> None:
        server = self._make_server()
        response = server._handle_request(
            {
                "jsonrpc": "2.0",
                "id": 9,
                "method": "tools/call",
                "params": {"name": "egtsr_inspect_obligations", "arguments": {}},
            }
        )

        self.assertTrue(response["result"]["isError"])
        self.assertIn("session_id is required", response["result"]["content"][0]["text"])

    def test_unknown_tool(self) -> None:
        server = self._make_server()
        response = server._handle_request(
            {
                "jsonrpc": "2.0",
                "id": 10,
                "method": "tools/call",
                "params": {"name": "egtsr_unknown", "arguments": {"session_id": SESSION_ID}},
            }
        )

        self.assertTrue(response["result"]["isError"])
        self.assertIn("Unknown tool", response["result"]["content"][0]["text"])

    def test_read_only(self) -> None:
        server = self._make_server()
        before = self._table_counts()

        for tool_name, arguments in [
            ("egtsr_inspect_obligations", {"session_id": SESSION_ID}),
            ("egtsr_inspect_stale", {"session_id": SESSION_ID}),
            ("egtsr_inspect_capsule", {"session_id": SESSION_ID}),
            ("egtsr_resume_status", {"session_id": SESSION_ID}),
            ("egtsr_session_summary", {"session_id": SESSION_ID}),
            ("egtsr_doctor", {"project_dir": self.tmp_dir.name}),
        ]:
            response = server._handle_request(
                {
                    "jsonrpc": "2.0",
                    "id": tool_name,
                    "method": "tools/call",
                    "params": {"name": tool_name, "arguments": arguments},
                }
            )
            self.assertNotIn("error", response)

        after = self._table_counts()
        self.assertEqual(before, after)
        self.assertEqual(Path(self.paths.resume_gate_path).read_text(encoding="utf-8"), "{}")
        self.assertEqual(Path(self.paths.last_good_capsule_path).read_text(encoding="utf-8"), "{}")

    def test_unknown_method(self) -> None:
        server = self._make_server()
        response = server._handle_request({"jsonrpc": "2.0", "id": 11, "method": "bogus/method", "params": {}})

        self.assertEqual(response["error"]["code"], -32601)
        self.assertIn("Method not found", response["error"]["message"])

    def _table_counts(self) -> dict[str, int]:
        conn = sqlite3.connect(self.config.db_path)
        try:
            return {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("sessions", "obligations", "invalidation_tickets", "capsules")
            }
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()

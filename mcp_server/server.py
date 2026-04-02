"""Minimal MCP server for EGTSR using JSON-RPC 2.0 over stdio.

Stdlib only. Supports a small MCP-compatible subset:
- initialize
- notifications/initialized
- tools/list
- tools/call
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, TextIO

from egtsr_runtime.db.runtime import SqliteRuntime
from egtsr_runtime.db.uow import SqliteUnitOfWork
from egtsr_runtime.mcp.inspect import InspectService
from egtsr_runtime.ops.health import HealthChecker
from egtsr_runtime.paths import RuntimePaths


class EGTSRMCPServer:
    def __init__(self, db_path: str | None = None, project_dir: str = "."):
        self._db_path = db_path
        self._project_dir = project_dir
        self._tools: dict[str, dict[str, Any]] = {}
        self._register_tools()

    def _register_tools(self) -> None:
        session_schema = {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID to inspect"}
            },
            "required": ["session_id"],
        }
        self._tools = {
            "egtsr_inspect_obligations": {
                "description": "Inspect open and verified obligations for a session",
                "inputSchema": session_schema,
            },
            "egtsr_inspect_stale": {
                "description": "Inspect stale invalidation tickets and revalidation queue",
                "inputSchema": session_schema,
            },
            "egtsr_inspect_capsule": {
                "description": "Inspect latest decision capsule and audit report",
                "inputSchema": session_schema,
            },
            "egtsr_resume_status": {
                "description": "Check resume gate status and blocking conditions",
                "inputSchema": session_schema,
            },
            "egtsr_doctor": {
                "description": "Run health diagnosis on EGTSR runtime",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "project_dir": {
                            "type": "string",
                            "description": "Project directory",
                            "default": ".",
                        }
                    },
                },
            },
            "egtsr_session_summary": {
                "description": "Get combined session overview with obligations, stale, capsule, and resume status",
                "inputSchema": session_schema,
            },
        }

    def run(self, stdin: TextIO | None = None, stdout: TextIO | None = None) -> None:
        """Main loop: read JSON-RPC from stdin, write responses to stdout."""
        input_stream = stdin or sys.stdin
        output_stream = stdout or sys.stdout
        self._use_content_length = True  # auto-detected on first message

        while True:
            request = self._read_message(input_stream)
            if request is None:
                break
            response = self._handle_request(request)
            if response is not None:
                body = json.dumps(response, ensure_ascii=False)
                if self._use_content_length:
                    output_stream.write(f"Content-Length: {len(body.encode('utf-8'))}\r\n\r\n{body}")
                else:
                    output_stream.write(body + "\n")
                output_stream.flush()

    def _read_message(self, stream: TextIO) -> dict[str, Any] | None:
        while True:
            line = stream.readline()
            if line == "":
                return None
            stripped = line.strip()
            if not stripped:
                continue

            if stripped.lower().startswith("content-length:"):
                self._use_content_length = True
                try:
                    content_length = int(stripped.split(":", 1)[1].strip())
                except ValueError:
                    return {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": "Invalid Content-Length header"},
                    }

                while True:
                    header_line = stream.readline()
                    if header_line == "":
                        return None
                    if header_line in {"\n", "\r\n"}:
                        break

                payload = stream.read(content_length)
                if not payload:
                    return None
                try:
                    request = json.loads(payload)
                except json.JSONDecodeError:
                    return {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": "Parse error"},
                    }
                return request if isinstance(request, dict) else {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}

            self._use_content_length = False
            try:
                request = json.loads(stripped)
            except json.JSONDecodeError:
                return {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": "Parse error"},
                }
            return request if isinstance(request, dict) else {"jsonrpc": "2.0", "id": None, "error": {"code": -32600, "message": "Invalid Request"}}

    def _handle_request(self, request: dict[str, Any]) -> dict[str, Any] | None:
        if "error" in request and request.get("jsonrpc") == "2.0":
            return request
        if request.get("jsonrpc") != "2.0":
            return self._error_response(request.get("id"), -32600, "Invalid Request")

        method = request.get("method")
        if not isinstance(method, str):
            return self._error_response(request.get("id"), -32600, "Invalid Request")

        req_id = request.get("id")
        params = request.get("params", {})
        if params is None:
            params = {}
        if not isinstance(params, dict):
            return self._error_response(req_id, -32602, "Invalid params")

        if method == "initialize":
            return self._handle_initialize(req_id)
        if method == "notifications/initialized":
            return None
        if method == "tools/list":
            return self._handle_tools_list(req_id)
        if method == "tools/call":
            return self._handle_tools_call(req_id, params)
        return self._error_response(req_id, -32601, f"Method not found: {method}")

    def _handle_initialize(self, req_id: Any) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "egtsr", "version": "0.1.1"},
            },
        }

    def _handle_tools_list(self, req_id: Any) -> dict[str, Any]:
        tools = [{"name": name, **spec} for name, spec in self._tools.items()]
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}}

    def _handle_tools_call(self, req_id: Any, params: dict[str, Any]) -> dict[str, Any]:
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})

        if not isinstance(tool_name, str) or not tool_name:
            return self._error_tool_result(req_id, "Tool name is required")
        if not isinstance(arguments, dict):
            return self._error_tool_result(req_id, "Tool arguments must be an object")

        try:
            result = self._execute_tool(tool_name, arguments)
        except Exception as exc:
            return self._error_tool_result(req_id, str(exc))

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [
                    {"type": "text", "text": json.dumps(result, indent=2, ensure_ascii=False)}
                ]
            },
        }

    def _execute_tool(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool_name not in self._tools:
            raise ValueError(f"Unknown tool: {tool_name}")

        if tool_name == "egtsr_doctor":
            project_dir = args.get("project_dir", self._project_dir)
            if not isinstance(project_dir, str) or not project_dir:
                raise ValueError("project_dir must be a non-empty string")
            paths = self._resolve_runtime_paths(project_dir)
            checker = HealthChecker()
            return checker.check(paths.db_path, paths.egtsr_dir)

        session_id = args.get("session_id")
        if not isinstance(session_id, str) or not session_id:
            raise ValueError("session_id is required")

        db_path = self._db_path or self._resolve_runtime_paths(self._project_dir).db_path
        runtime = SqliteRuntime(db_path)
        conn = runtime.boot()
        try:
            with SqliteUnitOfWork(conn) as uow:
                service = InspectService(uow)
                if tool_name == "egtsr_inspect_obligations":
                    return service.inspect_obligations(session_id)
                if tool_name == "egtsr_inspect_stale":
                    return service.inspect_stale(session_id)
                if tool_name == "egtsr_inspect_capsule":
                    return service.inspect_capsule(session_id)
                if tool_name == "egtsr_resume_status":
                    return service.resume_status(session_id)
                if tool_name == "egtsr_session_summary":
                    return {
                        "obligations": service.inspect_obligations(session_id),
                        "stale": service.inspect_stale(session_id),
                        "capsule": service.inspect_capsule(session_id),
                        "resume": service.resume_status(session_id),
                    }
        finally:
            runtime.shutdown()

        raise ValueError(f"Unknown tool: {tool_name}")

    @staticmethod
    def _resolve_runtime_paths(project_dir: str) -> RuntimePaths:
        from egtsr_runtime.runtime_locator import resolve_project_runtime_paths

        return resolve_project_runtime_paths(project_dir)

    def _error_tool_result(self, req_id: Any, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": f"Error: {message}"}],
                "isError": True,
            },
        }

    @staticmethod
    def _error_response(req_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--db-path", default=None)
    args = parser.parse_args()

    server = EGTSRMCPServer(db_path=args.db_path, project_dir=args.project_dir)
    server.run()


if __name__ == "__main__":
    main()

"""Minimal read-only local inspector server using stdlib http.server.
No external dependencies. All endpoints are GET only — no state mutation."""

from __future__ import annotations

import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer

from egtsr_runtime.db.uow import SqliteUnitOfWork
from egtsr_runtime.mcp.inspect import InspectService

# Route patterns: (pattern, service_method)
_ROUTES = [
    (re.compile(r"^/api/session/([^/]+)/obligations$"), "inspect_obligations"),
    (re.compile(r"^/api/session/([^/]+)/stale$"), "inspect_stale"),
    (re.compile(r"^/api/session/([^/]+)/capsule/latest$"), "inspect_capsule"),
    (re.compile(r"^/api/session/([^/]+)/resume-status$"), "resume_status"),
]


def _make_handler(db_path: str):
    """Return an InspectorHandler class bound to db_path."""

    class InspectorHandler(BaseHTTPRequestHandler):
        """Read-only HTTP handler. Routes GET requests to InspectService."""

        def do_GET(self) -> None:
            for pattern, method_name in _ROUTES:
                m = pattern.match(self.path)
                if m:
                    session_id = m.group(1)
                    with SqliteUnitOfWork(db_path) as uow:
                        service = InspectService(uow)
                        result = getattr(service, method_name)(session_id)
                    self._send_json(200, result)
                    return
            self._send_json(404, {"error": "Not found"})

        def do_POST(self) -> None:
            self._send_json(405, {"error": "Method Not Allowed"})

        def do_PUT(self) -> None:
            self._send_json(405, {"error": "Method Not Allowed"})

        def do_DELETE(self) -> None:
            self._send_json(405, {"error": "Method Not Allowed"})

        def _send_json(self, status: int, payload: dict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: object) -> None:  # noqa: ANN001
            # Silence default stderr logging
            pass

    return InspectorHandler


def start_inspector(db_path: str, host: str = "127.0.0.1", port: int = 9999) -> HTTPServer:
    """Start read-only inspector on localhost. Returns the server (caller must call serve_forever or handle_request)."""
    handler = _make_handler(db_path)
    server = HTTPServer((host, port), handler)
    return server

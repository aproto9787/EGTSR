"""Minimal read-only local inspector server using stdlib http.server.
No external dependencies. All endpoints are GET only — no state mutation."""

from __future__ import annotations

import html as html_mod
import json
import re
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from egtsr_runtime.db.runtime import SqliteRuntime
from egtsr_runtime.db.uow import SqliteUnitOfWork
from egtsr_runtime.mcp.inspect import InspectService

# JSON API routes (session_id in path)
_API_ROUTES = [
    (re.compile(r"^/api/session/([^/]+)/obligations$"), "inspect_obligations"),
    (re.compile(r"^/api/session/([^/]+)/stale$"), "inspect_stale"),
    (re.compile(r"^/api/session/([^/]+)/capsule/latest$"), "inspect_capsule"),
    (re.compile(r"^/api/session/([^/]+)/resume-status$"), "resume_status"),
]

_VIEW_PATHS = frozenset({"/", "/obligations", "/stale", "/capsule", "/verify"})

_E = html_mod.escape


def _wants_json(accept: str | None) -> bool:
    return accept is not None and "application/json" in accept


# ---------------------------------------------------------------------------
# HTML rendering helpers
# ---------------------------------------------------------------------------

def _layout(title: str, content: str, session_id: str | None = None) -> str:
    qs = f"?session={_E(session_id)}" if session_id else ""
    return (
        "<!DOCTYPE html><html lang=\"en\"><head><meta charset=\"UTF-8\">"
        f"<title>EGTSR Inspector — {_E(title)}</title>"
        "<style>"
        "*{box-sizing:border-box}"
        "body{font-family:ui-monospace,monospace;margin:0;background:#0d1117;color:#c9d1d9}"
        "nav{background:#161b22;padding:10px 24px;border-bottom:1px solid #30363d;display:flex;gap:20px;align-items:center}"
        "nav .brand{color:#58a6ff;font-weight:700;margin-right:8px}"
        "nav a{color:#8b949e;text-decoration:none;font-size:.9em}"
        "nav a:hover{color:#58a6ff}"
        "main{max-width:1100px;margin:0 auto;padding:24px}"
        "h1{color:#58a6ff;font-size:1.3em;margin:0 0 16px}"
        "h2{color:#8b949e;font-size:1em;border-bottom:1px solid #21262d;padding-bottom:6px}"
        "table{border-collapse:collapse;width:100%;margin:10px 0}"
        "th,td{border:1px solid #30363d;padding:6px 10px;text-align:left;font-size:.85em}"
        "th{background:#161b22;color:#8b949e}"
        "tr:hover{background:#161b22}"
        ".b{display:inline-block;padding:2px 8px;border-radius:10px;font-size:.78em;font-weight:600}"
        ".b-open,.b-fail{background:#da3633;color:#fff}"
        ".b-verified,.b-pass,.b-ok{background:#238636;color:#fff}"
        ".b-live{background:#d29922;color:#fff}"
        ".b-stale{background:#484f58;color:#c9d1d9}"
        ".b-blocked{background:#8957e5;color:#fff}"
        ".b-localized,.b-addressed,.b-reopened,.b-decision,.b-targeted{background:#1f6feb;color:#fff}"
        ".card{background:#161b22;padding:14px;border-radius:6px;border:1px solid #30363d;margin:10px 0}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin:14px 0}"
        ".stat{font-size:2em;font-weight:700;color:#58a6ff}"
        ".stat-sub{font-size:.82em;color:#8b949e;margin-top:2px}"
        "pre{background:#0d1117;border:1px solid #30363d;padding:10px;border-radius:4px;overflow-x:auto;font-size:.82em}"
        "a{color:#58a6ff;text-decoration:none}"
        "a:hover{text-decoration:underline}"
        ".empty{color:#484f58;font-style:italic;padding:20px;text-align:center}"
        "</style></head><body>"
        "<nav><span class=\"brand\">EGTSR</span>"
        f"<a href=\"/{qs}\">Summary</a>"
        f"<a href=\"/obligations{qs}\">Obligations</a>"
        f"<a href=\"/stale{qs}\">Stale</a>"
        f"<a href=\"/capsule{qs}\">Capsule</a>"
        f"<a href=\"/verify{qs}\">Verify</a></nav>"
        f"<main>{content}</main></body></html>"
    )


def _badge(value: str) -> str:
    cls = value.lower().replace(" ", "-")
    return f'<span class="b b-{_E(cls)}">{_E(value)}</span>'


def _render_session_list(sessions: dict) -> str:
    if sessions["count"] == 0:
        return '<h1>EGTSR Inspector</h1><div class="empty">No sessions found</div>'
    rows = "".join(
        f'<tr><td><a href="/?session={_E(s["id"])}">{_E(s["id"])}</a></td>'
        f'<td>{_E(s.get("branch") or "")}</td>'
        f'<td>{_E(s["status"])}</td>'
        f'<td>{_E(s["created_at"])}</td></tr>'
        for s in sessions["sessions"]
    )
    return (
        f"<h1>EGTSR Inspector</h1>"
        f'<h2>Sessions ({sessions["count"]})</h2>'
        f"<table><tr><th>ID</th><th>Branch</th><th>Status</th><th>Created</th></tr>"
        f"{rows}</table>"
    )


def _render_summary(data: dict, sessions: dict) -> str:
    sid = _E(data["session_id"])
    # Session selector if multiple sessions exist
    sel = ""
    if sessions["count"] > 1:
        opts = "".join(
            f'<a href="/?session={_E(s["id"])}" style="display:block;padding:4px 0">'
            f'{"&#x2192; " if s["id"] == data["session_id"] else ""}'
            f'{_E(s["id"][:20])} ({_E(s.get("branch") or "")}) — {_E(s["status"])}</a>'
            for s in sessions["sessions"]
        )
        sel = f'<div class="card"><h2>Sessions ({sessions["count"]})</h2>{opts}</div>'

    o = data["obligations"]
    s = data["stale"]
    c = data["capsule"]
    r = data["resume_gate"]
    v = data["verify"]
    gate = _badge("blocked" if r["edit_blocked"] else "ok")
    audit = _badge("pass" if c["latest_audit_pass"] else "fail") if c["latest_audit_pass"] is not None else "—"

    return (
        f"<h1>Summary — {sid}</h1>{sel}"
        '<div class="grid">'
        f'<div class="card"><div class="stat">{o["open"]}/{o["total"]}</div>'
        '<div class="stat-sub">Open Obligations</div></div>'
        f'<div class="card"><div class="stat">{s["live"]}</div>'
        '<div class="stat-sub">Live Stale Tickets</div></div>'
        f'<div class="card"><div class="stat">{c["count"]}</div>'
        f'<div class="stat-sub">Capsules {audit}</div></div>'
        f'<div class="card"><div class="stat">{v["result_count"]}</div>'
        '<div class="stat-sub">Verify Results</div></div>'
        f'<div class="card"><div class="stat">{v["family_count"]}</div>'
        '<div class="stat-sub">Attempt Families</div></div>'
        f'<div class="card"><div class="stat-sub">Resume Gate</div>{gate}'
        f'<div class="stat-sub">{_E(str(r["reason"] or ""))}</div></div>'
        "</div>"
    )


def _render_obligations(data: dict) -> str:
    sid = _E(data["session_id"])
    if not data["obligations"]:
        return f'<h1>Obligations — {sid}</h1><div class="empty">No obligations</div>'
    rows = "".join(
        f'<tr><td>{_E(o["id"])}</td><td>{_E(o["statement"])}</td>'
        f'<td>{o["priority"]}</td><td>{_badge(o["status"])}</td>'
        f'<td>{_E(o["created_at"])}</td></tr>'
        for o in data["obligations"]
    )
    return (
        f"<h1>Obligations — {sid}</h1>"
        f'<p>Total: {data["total_count"]} · Open: {data["open_count"]}</p>'
        "<table><tr><th>ID</th><th>Statement</th><th>Priority</th>"
        f"<th>Status</th><th>Created</th></tr>{rows}</table>"
    )


def _render_stale(data: dict) -> str:
    sid = _E(data["session_id"])

    def _ticket_rows(tickets: list) -> str:
        if not tickets:
            return '<tr><td colspan="5" class="empty">None</td></tr>'
        return "".join(
            f'<tr><td>{_E(str(t.get("id", "")))}</td>'
            f'<td>{_E(str(t.get("subject_type", "")))}</td>'
            f'<td>{_E(str(t.get("trigger_kind", "")))}</td>'
            f'<td>{_E(str(t.get("trigger_ref", "")))}</td>'
            f'<td>{_badge(str(t.get("status", "")))}</td></tr>'
            for t in tickets
        )

    hdr = "<tr><th>ID</th><th>Subject</th><th>Trigger</th><th>Ref</th><th>Status</th></tr>"
    return (
        f"<h1>Stale Queue — {sid}</h1>"
        f'<h2>Live ({data["live_count"]})</h2>'
        f"<table>{hdr}{_ticket_rows(data['live_tickets'])}</table>"
        f'<h2>Stale ({data["stale_count"]})</h2>'
        f"<table>{hdr}{_ticket_rows(data['stale_tickets'])}</table>"
    )


def _render_capsule(data: dict) -> str:
    sid = _E(data["session_id"])
    latest = data["latest"]
    if latest is None:
        return f'<h1>Capsule — {sid}</h1><div class="empty">No capsules</div>'
    audit = latest.get("audit_report") or {}
    return (
        f"<h1>Capsule — {sid}</h1>"
        f'<p>Total capsules: {data["capsule_count"]}</p>'
        '<div class="card">'
        f'<h2>Latest: {_E(latest["id"])}</h2>'
        "<table>"
        f'<tr><th>Phase</th><td>{_badge(latest["phase"])}</td></tr>'
        f'<tr><th>Tokens</th><td>{latest["token_count"]}</td></tr>'
        f'<tr><th>Audit</th><td>{_badge("pass" if latest["audit_pass"] else "fail")}</td></tr>'
        f'<tr><th>Created</th><td>{_E(latest["created_at"])}</td></tr>'
        "</table>"
        "<h2>Content Preview</h2>"
        f'<pre>{_E(latest.get("content_preview", ""))}</pre>'
        "<h2>Audit Report</h2>"
        f"<pre>{_E(json.dumps(audit, indent=2))}</pre>"
        "</div>"
    )


def _render_verify(data: dict) -> str:
    sid = _E(data["session_id"])

    if not data["verify_results"] and not data["attempt_families"]:
        return f'<h1>Verify — {sid}</h1><div class="empty">No verify results or attempt families</div>'

    vr_rows = "".join(
        f'<tr><td>{_E(r["id"])}</td><td>{_badge(r["phase"])}</td>'
        f'<td>{_badge(r["outcome"])}</td><td>{_E(r.get("excerpt") or "")}</td>'
        f'<td>{_E(r["created_at"])}</td></tr>'
        for r in data["verify_results"]
    )
    vr_table = (
        "<table><tr><th>ID</th><th>Phase</th><th>Outcome</th>"
        f"<th>Excerpt</th><th>Created</th></tr>{vr_rows}</table>"
        if data["verify_results"]
        else '<div class="empty">No verify results</div>'
    )

    af_rows = "".join(
        f'<tr><td>{_E(f["id"])}</td><td>{_E(f.get("obligation_id") or "—")}</td>'
        f'<td>{f["fail_count"]}</td><td>{_badge(f["last_outcome"])}</td>'
        f'<td>{_E(f.get("summary") or "")}</td><td>{_E(f["created_at"])}</td></tr>'
        for f in data["attempt_families"]
    )
    af_table = (
        "<table><tr><th>ID</th><th>Obligation</th><th>Fails</th>"
        f"<th>Outcome</th><th>Summary</th><th>Created</th></tr>{af_rows}</table>"
        if data["attempt_families"]
        else '<div class="empty">No attempt families</div>'
    )

    return (
        f"<h1>Verify — {sid}</h1>"
        f'<h2>Verify Results ({data["verify_count"]})</h2>{vr_table}'
        f'<h2>Attempt Families ({data["attempt_family_count"]})</h2>{af_table}'
    )


_RENDERERS = {
    "/obligations": _render_obligations,
    "/stale": _render_stale,
    "/capsule": _render_capsule,
    "/verify": _render_verify,
}


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------

def _make_handler(runtime: SqliteRuntime):
    """Return an InspectorHandler class bound to a booted runtime."""

    class InspectorHandler(BaseHTTPRequestHandler):
        """Read-only HTTP handler. Routes GET requests to InspectService."""

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            path = parsed.path.rstrip("/") or "/"
            params = parse_qs(parsed.query)

            # 1. JSON API routes
            for pattern, method_name in _API_ROUTES:
                m = pattern.match(path)
                if m:
                    session_id = m.group(1)
                    with SqliteUnitOfWork(runtime.connection()) as uow:
                        service = InspectService(uow)
                        result = getattr(service, method_name)(session_id)
                    self._send_json(200, result)
                    return

            # 2. View routes (HTML default, JSON with Accept header)
            if path in _VIEW_PATHS:
                self._handle_view(path, params)
                return

            self._send_json(404, {"error": "Not found"})

        def _handle_view(self, path: str, params: dict) -> None:
            session_id = params.get("session", [None])[0]
            accept = self.headers.get("Accept", "")
            use_json = _wants_json(accept)

            with SqliteUnitOfWork(runtime.connection()) as uow:
                service = InspectService(uow)

                if path == "/":
                    sessions = service.list_sessions()
                    summary = service.inspect_summary(session_id) if session_id else None
                else:
                    sessions = None
                    if not session_id:
                        summary = None
                    elif path == "/obligations":
                        summary = service.inspect_obligations(session_id)
                    elif path == "/stale":
                        summary = service.inspect_stale(session_id)
                    elif path == "/capsule":
                        summary = service.inspect_capsule(session_id)
                    elif path == "/verify":
                        summary = service.inspect_verify(session_id)
                    else:
                        summary = None

            # --- Root path ---
            if path == "/":
                if session_id and summary:
                    if use_json:
                        self._send_json(200, summary)
                    else:
                        self._send_html(
                            200,
                            _layout("Summary", _render_summary(summary, sessions), session_id),
                        )
                else:
                    if use_json:
                        self._send_json(200, sessions)
                    else:
                        self._send_html(200, _layout("Sessions", _render_session_list(sessions)))
                return

            # --- Detail pages require session ---
            if not session_id:
                if use_json:
                    self._send_json(400, {"error": "Missing ?session= parameter"})
                else:
                    self._send_html(
                        400,
                        _layout(
                            "Error",
                            '<div class="empty">Missing ?session= parameter. '
                            '<a href="/">Select a session</a></div>',
                        ),
                    )
                return

            if use_json:
                self._send_json(200, summary)
            else:
                content = _RENDERERS[path](summary)
                title = path.lstrip("/").title()
                self._send_html(200, _layout(title, content, session_id))

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

        def _send_html(self, status: int, html_content: str) -> None:
            body = html_content.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: object) -> None:  # noqa: ANN001
            pass

    return InspectorHandler


def start_inspector(db_path: str, host: str = "127.0.0.1", port: int = 9999) -> HTTPServer:
    """Start read-only inspector on localhost. Returns the server (caller must call serve_forever or handle_request)."""
    runtime = SqliteRuntime(db_path)
    runtime.boot()
    handler = _make_handler(runtime)
    server = HTTPServer((host, port), handler)
    server._egtsr_runtime = runtime  # type: ignore[attr-defined]
    return server

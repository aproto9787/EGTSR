from __future__ import annotations

import json
import tempfile
import threading
import unittest
from http.client import HTTPConnection

from egtsr_runtime.config import RuntimeConfig
from egtsr_runtime.db.uow import SqliteUnitOfWork
from egtsr_runtime.enums import InvalidationStatus, ObligationStatus, VerifyPhase
from egtsr_runtime.models import (
    AttemptFamily,
    Capsule,
    InvalidationTicket,
    Obligation,
    Session,
    VerifyResult,
)
from egtsr_runtime.paths import ensure_runtime_dirs
from egtsr_runtime.ui.server import start_inspector

SESSION_ID = "ui-test-session-1"


def _make_config(tmp_dir: str) -> RuntimeConfig:
    paths = ensure_runtime_dirs(tmp_dir)
    return RuntimeConfig(
        repo_root=paths.repo_root,
        egtsr_dir=paths.egtsr_dir,
        db_path=paths.db_path,
    )


def _seed_data(config: RuntimeConfig) -> None:
    with SqliteUnitOfWork(config) as uow:
        uow.sessions.create(
            Session(
                id=SESSION_ID,
                repo_root="/tmp/repo",
                branch="main",
                head_hash="abc123",
                status="active",
                created_at="2026-03-31T09:00:00Z",
                updated_at="2026-03-31T09:00:00Z",
            )
        )
        uow.obligations.upsert(
            Obligation(
                id="obl-ui-1",
                session_id=SESSION_ID,
                source="spec",
                statement="UI test obligation",
                priority=50,
                status=ObligationStatus.OPEN,
                created_at="2026-03-31T09:01:00Z",
                updated_at="2026-03-31T09:01:00Z",
            )
        )
        uow.invalidations.upsert(
            InvalidationTicket(
                id="inv-ui-1",
                session_id=SESSION_ID,
                subject_type="assertion",
                subject_id="as-1",
                trigger_kind="file_change",
                trigger_ref="src/foo.py",
                status=InvalidationStatus.LIVE,
                metadata={},
                created_at="2026-03-31T09:02:00Z",
                updated_at="2026-03-31T09:02:00Z",
            )
        )
        uow.capsules.create(
            Capsule(
                id="cap-ui-1",
                session_id=SESSION_ID,
                phase=VerifyPhase.DECISION,
                frontier_hash="frontier-ui",
                content="ui capsule content",
                token_count=77,
                audit_pass=True,
                audit_report={"passed": True},
                created_at="2026-03-31T09:03:00Z",
            )
        )
        uow.verify_results.create(
            VerifyResult(
                id="vr-ui-1",
                session_id=SESSION_ID,
                phase=VerifyPhase.DECISION,
                outcome="pass",
                affected_obligation_ids=["obl-ui-1"],
                excerpt="All tests passed",
                metadata={},
                created_at="2026-03-31T09:04:00Z",
            )
        )
        uow.attempt_families.upsert(
            AttemptFamily(
                id="af-ui-1",
                session_id=SESSION_ID,
                obligation_id="obl-ui-1",
                signature="sig-1",
                touched_scope=["src/foo.py"],
                fail_count=2,
                last_outcome="fail",
                summary="Repeated failure in foo",
                metadata={},
                created_at="2026-03-31T09:05:00Z",
                updated_at="2026-03-31T09:05:00Z",
            )
        )
        uow.commit()


class TestUIInspector(unittest.TestCase):
    server = None
    thread = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmp_dir = tempfile.TemporaryDirectory()
        cls.config = _make_config(cls.tmp_dir.name)
        _seed_data(cls.config)
        # Start server on a random available port
        cls.server = start_inspector(cls.config.db_path, host="127.0.0.1", port=0)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.tmp_dir.cleanup()

    def _get(self, path: str):
        conn = HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = json.loads(resp.read())
        conn.close()
        return resp.status, body

    def _get_html(self, path: str):
        """GET request, expect HTML response. Returns (status, body_str, content_type)."""
        conn = HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read().decode("utf-8")
        ct = resp.getheader("Content-Type", "")
        conn.close()
        return resp.status, body, ct

    def _get_json_accept(self, path: str):
        """GET with Accept: application/json. Returns (status, parsed_json, content_type)."""
        conn = HTTPConnection("127.0.0.1", self.port)
        conn.request("GET", path, headers={"Accept": "application/json"})
        resp = conn.getresponse()
        body = json.loads(resp.read())
        ct = resp.getheader("Content-Type", "")
        conn.close()
        return resp.status, body, ct

    def _method(self, method: str, path: str):
        conn = HTTPConnection("127.0.0.1", self.port)
        conn.request(method, path)
        resp = conn.getresponse()
        body = json.loads(resp.read())
        conn.close()
        return resp.status, body

    # ------------------------------------------------------------------
    # Existing API tests
    # ------------------------------------------------------------------

    def test_get_obligations_returns_json(self) -> None:
        """GET /api/session/{id}/obligations returns JSON with obligations."""
        status, body = self._get(f"/api/session/{SESSION_ID}/obligations")
        self.assertEqual(status, 200)
        self.assertEqual(body["session_id"], SESSION_ID)
        self.assertIn("total_count", body)
        self.assertEqual(body["total_count"], 1)

    def test_get_stale_returns_json(self) -> None:
        """GET /api/session/{id}/stale returns JSON with ticket counts."""
        status, body = self._get(f"/api/session/{SESSION_ID}/stale")
        self.assertEqual(status, 200)
        self.assertIn("live_count", body)
        self.assertEqual(body["live_count"], 1)

    def test_get_capsule_returns_json(self) -> None:
        """GET /api/session/{id}/capsule/latest returns latest capsule."""
        status, body = self._get(f"/api/session/{SESSION_ID}/capsule/latest")
        self.assertEqual(status, 200)
        self.assertIsNotNone(body["latest"])
        self.assertEqual(body["latest"]["id"], "cap-ui-1")

    def test_get_resume_status_returns_json(self) -> None:
        """GET /api/session/{id}/resume-status returns gate state."""
        status, body = self._get(f"/api/session/{SESSION_ID}/resume-status")
        self.assertEqual(status, 200)
        self.assertIn("edit_blocked", body)

    def test_post_returns_405(self) -> None:
        """POST request returns 405 Method Not Allowed."""
        status, body = self._method("POST", f"/api/session/{SESSION_ID}/obligations")
        self.assertEqual(status, 405)
        self.assertIn("error", body)

    def test_put_returns_405(self) -> None:
        """PUT request returns 405 Method Not Allowed."""
        status, body = self._method("PUT", f"/api/session/{SESSION_ID}/obligations")
        self.assertEqual(status, 405)

    def test_delete_returns_405(self) -> None:
        """DELETE request returns 405 Method Not Allowed."""
        status, body = self._method("DELETE", f"/api/session/{SESSION_ID}/obligations")
        self.assertEqual(status, 405)

    def test_unknown_route_returns_404(self) -> None:
        """Unknown route returns 404."""
        status, body = self._get("/api/unknown/route")
        self.assertEqual(status, 404)

    def test_read_only_no_db_mutation(self) -> None:
        """All GET calls leave DB state unchanged."""
        self._get(f"/api/session/{SESSION_ID}/obligations")
        self._get(f"/api/session/{SESSION_ID}/stale")
        self._get(f"/api/session/{SESSION_ID}/capsule/latest")
        self._get(f"/api/session/{SESSION_ID}/resume-status")

        with SqliteUnitOfWork(self.config) as uow:
            obls = uow.obligations.list_for_session(SESSION_ID)
            tickets = uow.invalidations.list_for_session(SESSION_ID)
            capsules = uow.capsules.list_for_session(SESSION_ID)

        self.assertEqual(len(obls), 1)
        self.assertEqual(obls[0].status, ObligationStatus.OPEN)
        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0].status, InvalidationStatus.LIVE)
        self.assertEqual(len(capsules), 1)

    # ------------------------------------------------------------------
    # View: root (session list / summary)
    # ------------------------------------------------------------------

    def test_view_root_html_session_list(self) -> None:
        """GET / returns HTML session list when no session param."""
        status, body, ct = self._get_html("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ct)
        self.assertIn(SESSION_ID, body)
        self.assertIn("EGTSR Inspector", body)

    def test_view_root_json_session_list(self) -> None:
        """GET / with Accept:json returns session list as JSON."""
        status, body, ct = self._get_json_accept("/")
        self.assertEqual(status, 200)
        self.assertIn("application/json", ct)
        self.assertEqual(body["count"], 1)
        self.assertEqual(body["sessions"][0]["id"], SESSION_ID)

    def test_view_summary_html(self) -> None:
        """GET /?session=X returns HTML summary dashboard."""
        status, body, ct = self._get_html(f"/?session={SESSION_ID}")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ct)
        self.assertIn("Summary", body)
        self.assertIn("Obligations", body)

    def test_view_summary_json(self) -> None:
        """GET /?session=X with Accept:json returns JSON summary."""
        status, body, ct = self._get_json_accept(f"/?session={SESSION_ID}")
        self.assertEqual(status, 200)
        self.assertIn("application/json", ct)
        self.assertEqual(body["session_id"], SESSION_ID)
        self.assertIn("obligations", body)
        self.assertEqual(body["obligations"]["total"], 1)

    # ------------------------------------------------------------------
    # View: obligations
    # ------------------------------------------------------------------

    def test_view_obligations_html(self) -> None:
        """GET /obligations?session=X returns HTML with obligation data."""
        status, body, ct = self._get_html(f"/obligations?session={SESSION_ID}")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ct)
        self.assertIn("obl-ui-1", body)
        self.assertIn("UI test obligation", body)

    def test_view_obligations_json(self) -> None:
        """GET /obligations?session=X with Accept:json returns JSON."""
        status, body, ct = self._get_json_accept(f"/obligations?session={SESSION_ID}")
        self.assertEqual(status, 200)
        self.assertEqual(body["total_count"], 1)

    # ------------------------------------------------------------------
    # View: stale
    # ------------------------------------------------------------------

    def test_view_stale_html(self) -> None:
        """GET /stale?session=X returns HTML with stale data."""
        status, body, ct = self._get_html(f"/stale?session={SESSION_ID}")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ct)
        self.assertIn("inv-ui-1", body)

    def test_view_stale_json(self) -> None:
        """GET /stale?session=X with Accept:json returns JSON."""
        status, body, ct = self._get_json_accept(f"/stale?session={SESSION_ID}")
        self.assertEqual(status, 200)
        self.assertEqual(body["live_count"], 1)

    # ------------------------------------------------------------------
    # View: capsule
    # ------------------------------------------------------------------

    def test_view_capsule_html(self) -> None:
        """GET /capsule?session=X returns HTML with capsule data."""
        status, body, ct = self._get_html(f"/capsule?session={SESSION_ID}")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ct)
        self.assertIn("cap-ui-1", body)
        self.assertIn("ui capsule content", body)

    def test_view_capsule_json(self) -> None:
        """GET /capsule?session=X with Accept:json returns JSON."""
        status, body, ct = self._get_json_accept(f"/capsule?session={SESSION_ID}")
        self.assertEqual(status, 200)
        self.assertEqual(body["latest"]["id"], "cap-ui-1")

    # ------------------------------------------------------------------
    # View: verify
    # ------------------------------------------------------------------

    def test_view_verify_html(self) -> None:
        """GET /verify?session=X returns HTML with verify data."""
        status, body, ct = self._get_html(f"/verify?session={SESSION_ID}")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ct)
        self.assertIn("vr-ui-1", body)
        self.assertIn("af-ui-1", body)

    def test_view_verify_json(self) -> None:
        """GET /verify?session=X with Accept:json returns JSON."""
        status, body, ct = self._get_json_accept(f"/verify?session={SESSION_ID}")
        self.assertEqual(status, 200)
        self.assertEqual(body["verify_count"], 1)
        self.assertEqual(body["verify_results"][0]["id"], "vr-ui-1")
        self.assertEqual(body["attempt_family_count"], 1)
        self.assertEqual(body["attempt_families"][0]["id"], "af-ui-1")

    # ------------------------------------------------------------------
    # View: error cases
    # ------------------------------------------------------------------

    def test_view_missing_session_returns_400_html(self) -> None:
        """Detail view without ?session= returns 400 HTML."""
        status, body, ct = self._get_html("/obligations")
        self.assertEqual(status, 400)
        self.assertIn("text/html", ct)
        self.assertIn("Missing", body)

    def test_view_missing_session_returns_400_json(self) -> None:
        """Detail view without ?session= returns 400 JSON."""
        status, body, ct = self._get_json_accept("/obligations")
        self.assertEqual(status, 400)
        self.assertIn("error", body)

    # ------------------------------------------------------------------
    # Read-only verification (views don't mutate)
    # ------------------------------------------------------------------

    def test_views_read_only(self) -> None:
        """All view GETs leave DB state unchanged."""
        self._get_html("/")
        self._get_html(f"/?session={SESSION_ID}")
        self._get_html(f"/obligations?session={SESSION_ID}")
        self._get_html(f"/stale?session={SESSION_ID}")
        self._get_html(f"/capsule?session={SESSION_ID}")
        self._get_html(f"/verify?session={SESSION_ID}")

        with SqliteUnitOfWork(self.config) as uow:
            obls = uow.obligations.list_for_session(SESSION_ID)
            tickets = uow.invalidations.list_for_session(SESSION_ID)
            capsules = uow.capsules.list_for_session(SESSION_ID)
            vrs = uow.verify_results.list_for_session(SESSION_ID)
            afs = uow.attempt_families.list_for_session(SESSION_ID)

        self.assertEqual(len(obls), 1)
        self.assertEqual(len(tickets), 1)
        self.assertEqual(len(capsules), 1)
        self.assertEqual(len(vrs), 1)
        self.assertEqual(len(afs), 1)


if __name__ == "__main__":
    unittest.main()

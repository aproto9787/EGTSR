from __future__ import annotations

import tempfile
import unittest

from egtsr_runtime.config import RuntimeConfig
from egtsr_runtime.db.uow import SqliteUnitOfWork
from egtsr_runtime.enums import InvalidationStatus, ObligationStatus, VerifyPhase
from egtsr_runtime.mcp.handlers import handle_mcp_tool
from egtsr_runtime.mcp.inspect import InspectService
from egtsr_runtime.models import Capsule, InvalidationTicket, Obligation, Session
from egtsr_runtime.paths import ensure_runtime_dirs


SESSION_ID = "mcp-test-session-1"


def _make_config(tmp_dir: str) -> RuntimeConfig:
    paths = ensure_runtime_dirs(tmp_dir)
    return RuntimeConfig(
        repo_root=paths.repo_root,
        egtsr_dir=paths.egtsr_dir,
        db_path=paths.db_path,
    )


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


def _seed_ticket(
    uow: SqliteUnitOfWork,
    session_id: str,
    ticket_id: str,
    status: InvalidationStatus,
) -> None:
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


class TestMCPInspect(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.config = _make_config(self.tmp_dir.name)

    def tearDown(self) -> None:
        self.tmp_dir.cleanup()

    # ------------------------------------------------------------------
    # inspect_obligations
    # ------------------------------------------------------------------

    def test_inspect_obligations_returns_all(self) -> None:
        """inspect_obligations returns correct counts and obligation list."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow, SESSION_ID)
            _seed_obligation(uow, SESSION_ID, "obl-1", ObligationStatus.OPEN)
            _seed_obligation(uow, SESSION_ID, "obl-2", ObligationStatus.VERIFIED)
            uow.commit()

        with SqliteUnitOfWork(self.config) as uow:
            service = InspectService(uow)
            result = service.inspect_obligations(SESSION_ID)

        self.assertEqual(result["session_id"], SESSION_ID)
        self.assertEqual(result["total_count"], 2)
        self.assertEqual(result["open_count"], 1)
        ids = {o["id"] for o in result["obligations"]}
        self.assertEqual(ids, {"obl-1", "obl-2"})
        self.assertIn("query_timestamp", result)

    def test_inspect_obligations_empty_session(self) -> None:
        """Empty session returns zero counts."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow, SESSION_ID)
            uow.commit()

        with SqliteUnitOfWork(self.config) as uow:
            service = InspectService(uow)
            result = service.inspect_obligations(SESSION_ID)

        self.assertEqual(result["total_count"], 0)
        self.assertEqual(result["open_count"], 0)
        self.assertEqual(result["obligations"], [])

    # ------------------------------------------------------------------
    # inspect_stale
    # ------------------------------------------------------------------

    def test_inspect_stale_returns_tickets(self) -> None:
        """inspect_stale returns live/stale ticket counts."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow, SESSION_ID)
            _seed_ticket(uow, SESSION_ID, "inv-live-1", InvalidationStatus.LIVE)
            _seed_ticket(uow, SESSION_ID, "inv-stale-1", InvalidationStatus.STALE)
            uow.commit()

        with SqliteUnitOfWork(self.config) as uow:
            service = InspectService(uow)
            result = service.inspect_stale(SESSION_ID)

        self.assertEqual(result["session_id"], SESSION_ID)
        self.assertEqual(result["live_count"], 1)
        self.assertEqual(result["stale_count"], 1)
        self.assertEqual(len(result["live_tickets"]), 1)
        self.assertEqual(len(result["stale_tickets"]), 1)
        self.assertEqual(result["live_tickets"][0]["id"], "inv-live-1")
        self.assertIn("query_timestamp", result)

    def test_inspect_stale_empty(self) -> None:
        """No tickets returns zero counts."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow, SESSION_ID)
            uow.commit()

        with SqliteUnitOfWork(self.config) as uow:
            service = InspectService(uow)
            result = service.inspect_stale(SESSION_ID)

        self.assertEqual(result["live_count"], 0)
        self.assertEqual(result["stale_count"], 0)
        self.assertEqual(result["live_tickets"], [])
        self.assertEqual(result["stale_tickets"], [])

    # ------------------------------------------------------------------
    # inspect_capsule
    # ------------------------------------------------------------------

    def test_inspect_capsule_returns_latest(self) -> None:
        """inspect_capsule returns most recent capsule with audit."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow, SESSION_ID)
            _seed_capsule(uow, SESSION_ID, "cap-1", audit_pass=True)
            uow.commit()

        with SqliteUnitOfWork(self.config) as uow:
            service = InspectService(uow)
            result = service.inspect_capsule(SESSION_ID)

        self.assertEqual(result["session_id"], SESSION_ID)
        self.assertEqual(result["capsule_count"], 1)
        self.assertIsNotNone(result["latest"])
        self.assertEqual(result["latest"]["id"], "cap-1")
        self.assertEqual(result["latest"]["phase"], "decision")
        self.assertTrue(result["latest"]["audit_pass"])
        self.assertIn("capsule content", result["latest"]["content_preview"])
        self.assertIn("query_timestamp", result)

    def test_inspect_capsule_no_capsules(self) -> None:
        """No capsules returns None for latest."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow, SESSION_ID)
            uow.commit()

        with SqliteUnitOfWork(self.config) as uow:
            service = InspectService(uow)
            result = service.inspect_capsule(SESSION_ID)

        self.assertEqual(result["capsule_count"], 0)
        self.assertIsNone(result["latest"])

    # ------------------------------------------------------------------
    # resume_status
    # ------------------------------------------------------------------

    def test_resume_status_shows_gate(self) -> None:
        """resume_status returns gate state."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow, SESSION_ID)
            uow.commit()

        with SqliteUnitOfWork(self.config) as uow:
            service = InspectService(uow)
            result = service.resume_status(SESSION_ID)

        self.assertEqual(result["session_id"], SESSION_ID)
        self.assertIn("edit_blocked", result)
        self.assertIn("reason", result)
        self.assertIn("required_rechecks", result)
        self.assertIn("query_timestamp", result)
        # No live tickets, not a resume source — gate should not be blocked
        self.assertFalse(result["edit_blocked"])

    # ------------------------------------------------------------------
    # handle_mcp_tool dispatch
    # ------------------------------------------------------------------

    def test_mcp_handler_dispatch(self) -> None:
        """handle_mcp_tool dispatches correctly."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow, SESSION_ID)
            uow.commit()

        result = handle_mcp_tool(
            "inspect_obligations",
            {"session_id": SESSION_ID},
            self.config.db_path,
        )
        self.assertEqual(result["session_id"], SESSION_ID)
        self.assertIn("total_count", result)

        result2 = handle_mcp_tool(
            "inspect_stale",
            {"session_id": SESSION_ID},
            self.config.db_path,
        )
        self.assertIn("live_count", result2)

        result3 = handle_mcp_tool(
            "inspect_capsule",
            {"session_id": SESSION_ID},
            self.config.db_path,
        )
        self.assertIn("capsule_count", result3)

        result4 = handle_mcp_tool(
            "resume_status",
            {"session_id": SESSION_ID},
            self.config.db_path,
        )
        self.assertIn("edit_blocked", result4)

    def test_all_endpoints_read_only(self) -> None:
        """Verify no DB mutations after inspect calls."""
        with SqliteUnitOfWork(self.config) as uow:
            _seed_session(uow, SESSION_ID)
            _seed_obligation(uow, SESSION_ID, "obl-ro", ObligationStatus.OPEN)
            _seed_ticket(uow, SESSION_ID, "inv-ro", InvalidationStatus.LIVE)
            _seed_capsule(uow, SESSION_ID, "cap-ro")
            uow.commit()

        with SqliteUnitOfWork(self.config) as uow:
            service = InspectService(uow)
            service.inspect_obligations(SESSION_ID)
            service.inspect_stale(SESSION_ID)
            service.inspect_capsule(SESSION_ID)
            service.resume_status(SESSION_ID)
            # No commit called — all read-only; conn.in_transaction should be False
            self.assertFalse(uow.conn.in_transaction)

        # Verify DB state is unchanged
        with SqliteUnitOfWork(self.config) as uow:
            obls = uow.obligations.list_for_session(SESSION_ID)
            tickets = uow.invalidations.list_for_session(SESSION_ID)
            capsules = uow.capsules.list_for_session(SESSION_ID)

        self.assertEqual(len(obls), 1)
        self.assertEqual(obls[0].id, "obl-ro")
        self.assertEqual(obls[0].status, ObligationStatus.OPEN)
        self.assertEqual(len(tickets), 1)
        self.assertEqual(tickets[0].status, InvalidationStatus.LIVE)
        self.assertEqual(len(capsules), 1)

    def test_unknown_tool_returns_error(self) -> None:
        """Unknown tool name returns error dict."""
        result = handle_mcp_tool(
            "nonexistent_tool",
            {"session_id": SESSION_ID},
            self.config.db_path,
        )
        self.assertIn("error", result)
        self.assertIn("nonexistent_tool", result["error"])


if __name__ == "__main__":
    unittest.main()

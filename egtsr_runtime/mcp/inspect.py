from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone

from egtsr_runtime.enums import InvalidationStatus, ObligationStatus


class InspectService:
    def __init__(self, uow) -> None:
        self._uow = uow

    def inspect_obligations(self, session_id: str) -> dict:
        """Return all obligations with counts. Read-only."""
        obligations = self._uow.obligations.list_for_session(session_id)
        open_obls = [o for o in obligations if o.status != ObligationStatus.VERIFIED]
        return {
            "session_id": session_id,
            "total_count": len(obligations),
            "open_count": len(open_obls),
            "obligations": [
                {
                    "id": o.id,
                    "statement": o.statement,
                    "priority": o.priority,
                    "status": o.status.value if hasattr(o.status, "value") else str(o.status),
                    "created_at": o.created_at,
                }
                for o in obligations
            ],
            "query_timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def inspect_stale(self, session_id: str) -> dict:
        """Return invalidation tickets grouped by status. Read-only."""
        tickets = self._uow.invalidations.list_for_session(session_id)
        live = [t for t in tickets if t.status == InvalidationStatus.LIVE]
        stale = [t for t in tickets if t.status == InvalidationStatus.STALE]
        return {
            "session_id": session_id,
            "live_count": len(live),
            "stale_count": len(stale),
            "live_tickets": [asdict(t) for t in live] if live else [],
            "stale_tickets": [asdict(t) for t in stale] if stale else [],
            "query_timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def inspect_capsule(self, session_id: str) -> dict:
        """Return latest capsule and audit report. Read-only."""
        capsules = self._uow.capsules.list_for_session(session_id)
        latest = capsules[-1] if capsules else None
        return {
            "session_id": session_id,
            "capsule_count": len(capsules),
            "latest": {
                "id": latest.id,
                "phase": latest.phase.value if hasattr(latest.phase, "value") else str(latest.phase),
                "token_count": latest.token_count,
                "audit_pass": latest.audit_pass,
                "audit_report": latest.audit_report,
                "content_preview": latest.content[:500] if latest.content else "",
                "created_at": latest.created_at,
            }
            if latest is not None
            else None,
            "query_timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def resume_status(self, session_id: str) -> dict:
        """Return resume gate status. Read-only."""
        from egtsr_runtime.services.resume_gate import ResumeGateService

        gate_service = ResumeGateService(self._uow)
        gate = gate_service.evaluate(session_id, source=None)
        return {
            "session_id": session_id,
            "edit_blocked": gate.edit_blocked,
            "reason": gate.reason,
            "required_rechecks": gate.required_rechecks,
            "query_timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def list_sessions(self) -> dict:
        """Return all sessions ordered by creation time. Read-only."""
        rows = self._uow.conn.execute(
            "SELECT id, repo_root, branch, status, created_at "
            "FROM sessions ORDER BY created_at DESC"
        ).fetchall()
        return {
            "sessions": [
                {
                    "id": r["id"],
                    "repo_root": r["repo_root"],
                    "branch": r["branch"],
                    "status": r["status"],
                    "created_at": r["created_at"],
                }
                for r in rows
            ],
            "count": len(rows),
            "query_timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def inspect_verify(self, session_id: str) -> dict:
        """Return verify results and attempt families. Read-only."""
        results = self._uow.verify_results.list_for_session(session_id)
        families = self._uow.attempt_families.list_for_session(session_id)
        return {
            "session_id": session_id,
            "verify_count": len(results),
            "verify_results": [
                {
                    "id": r.id,
                    "phase": r.phase.value if hasattr(r.phase, "value") else str(r.phase),
                    "outcome": r.outcome,
                    "affected_obligation_ids": r.affected_obligation_ids,
                    "excerpt": r.excerpt,
                    "created_at": r.created_at,
                }
                for r in results
            ],
            "attempt_family_count": len(families),
            "attempt_families": [
                {
                    "id": f.id,
                    "obligation_id": f.obligation_id,
                    "signature": f.signature,
                    "fail_count": f.fail_count,
                    "last_outcome": f.last_outcome,
                    "summary": f.summary,
                    "created_at": f.created_at,
                }
                for f in families
            ],
            "query_timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def inspect_summary(self, session_id: str) -> dict:
        """Return aggregate summary for a session. Read-only."""
        obls = self.inspect_obligations(session_id)
        stale = self.inspect_stale(session_id)
        capsule = self.inspect_capsule(session_id)
        resume = self.resume_status(session_id)
        verify = self.inspect_verify(session_id)
        return {
            "session_id": session_id,
            "obligations": {"total": obls["total_count"], "open": obls["open_count"]},
            "stale": {"live": stale["live_count"], "stale": stale["stale_count"]},
            "capsule": {
                "count": capsule["capsule_count"],
                "latest_phase": capsule["latest"]["phase"] if capsule["latest"] else None,
                "latest_audit_pass": capsule["latest"]["audit_pass"] if capsule["latest"] else None,
            },
            "resume_gate": {
                "edit_blocked": resume["edit_blocked"],
                "reason": resume["reason"],
            },
            "verify": {
                "result_count": verify["verify_count"],
                "family_count": verify["attempt_family_count"],
            },
            "query_timestamp": datetime.now(timezone.utc).isoformat(),
        }

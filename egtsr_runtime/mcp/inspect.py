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

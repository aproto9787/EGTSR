from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from egtsr_runtime.enums import InvalidationStatus


@dataclass(slots=True)
class ResumeGateState:
    session_id: str
    edit_blocked: bool = False
    reason: str | None = None
    required_rechecks: list[str] = field(default_factory=list)
    updated_at: str = ""


class ResumeGateService:
    def __init__(self, uow):
        self._uow = uow

    def evaluate(
        self,
        session_id: str,
        source: str | None,
        repo_dirty: bool = False,
    ) -> ResumeGateState:
        """Evaluate resume gate on SessionStart and prompt entry."""

        now = datetime.now(timezone.utc).isoformat()
        gate = ResumeGateState(session_id=session_id, updated_at=now)
        is_resume = source in {"resume", "compact"}

        db_healthy = True
        live_tickets = []

        try:
            live_tickets = [
                ticket
                for ticket in self._uow.invalidations.list_for_session(session_id)
                if ticket.status == InvalidationStatus.LIVE
            ]
        except Exception:
            db_healthy = False

        try:
            self._uow.sessions.get(session_id)
        except Exception:
            db_healthy = False

        should_enter = is_resume or repo_dirty or bool(live_tickets) or not db_healthy
        if not should_enter:
            return gate

        rechecks: list[str] = []
        if repo_dirty:
            rechecks.append("repo_dirty")
        if not db_healthy:
            rechecks.append("db_health_check_failed")
        for ticket in live_tickets:
            rechecks.append(f"ticket:{ticket.id}")

        gate.edit_blocked = True
        gate.required_rechecks = rechecks
        gate.reason = self._build_reason(
            source=source,
            is_resume=is_resume,
            repo_dirty=repo_dirty,
            live_tickets=live_tickets,
            db_healthy=db_healthy,
        )
        return gate

    @staticmethod
    def should_block_prompt(gate: ResumeGateState, prompt_intent: str) -> bool:
        """Block edit/mixed while the gate is active."""

        if not gate.edit_blocked:
            return False
        if prompt_intent in {"read", "inspect", "test"}:
            return False
        return True

    @staticmethod
    def _build_reason(
        *,
        source: str | None,
        is_resume: bool,
        repo_dirty: bool,
        live_tickets: list[object],
        db_healthy: bool,
    ) -> str:
        reasons: list[str] = []
        if is_resume:
            reasons.append(f"source={source or 'resume'}")
        if repo_dirty:
            reasons.append("repo_dirty")
        if live_tickets:
            reasons.append(f"live_tickets={len(live_tickets)}")
        if not db_healthy:
            reasons.append("db_health_check_failed")
        if not reasons:
            reasons.append("manual_review_required")
        return "Resume gate active: " + ", ".join(reasons)

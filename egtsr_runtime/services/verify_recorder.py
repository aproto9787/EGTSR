from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from egtsr_runtime.enums import ObligationStatus, VerifyPhase
from egtsr_runtime.models import Event, VerifyResult


@dataclass(slots=True)
class VerifyTransitionResult:
    verify_result_id: str
    reopened_obligation_ids: list[str] = field(default_factory=list)
    next_phase: str | None = None


class VerifyResultsRecorder:
    def __init__(self, uow):
        self._uow = uow

    def record(
        self,
        session_id: str,
        phase: str,
        outcome: str,
        affected_obligation_ids: list[str],
        excerpt: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> VerifyTransitionResult:
        """Record a verify result and apply transitions."""

        created_at = datetime.now(timezone.utc).isoformat()
        phase_enum = VerifyPhase(phase)
        affected_ids = list(affected_obligation_ids)
        result = VerifyResult(
            id=uuid.uuid4().hex,
            session_id=session_id,
            phase=phase_enum,
            outcome=outcome,
            affected_obligation_ids=affected_ids,
            excerpt=excerpt,
            metadata=dict(metadata or {}),
            created_at=created_at,
        )
        self._uow.verify_results.create(result)

        reopened_ids: list[str] = []
        if self._is_fail(outcome):
            for obligation_id in affected_ids:
                obligation = self._uow.obligations.get(obligation_id)
                if obligation is None:
                    continue
                if obligation.status not in {ObligationStatus.ADDRESSED, ObligationStatus.LOCALIZED}:
                    continue
                self._uow.obligations.mark_status(obligation_id, ObligationStatus.REOPENED.value)
                reopened_ids.append(obligation_id)

        next_phase = self._derive_next_phase(phase_enum, outcome)
        self._uow.events.create(
            Event(
                id=uuid.uuid4().hex,
                session_id=session_id,
                event_type="verify_result.recorded",
                payload={
                    "verify_result_id": result.id,
                    "phase": phase_enum.value,
                    "outcome": outcome,
                    "affected_obligation_ids": affected_ids,
                    "reopened_obligation_ids": reopened_ids,
                    "next_phase": next_phase,
                },
                created_at=created_at,
            )
        )
        return VerifyTransitionResult(
            verify_result_id=result.id,
            reopened_obligation_ids=reopened_ids,
            next_phase=next_phase,
        )

    @staticmethod
    def _derive_next_phase(phase: VerifyPhase, outcome: str) -> str | None:
        if VerifyResultsRecorder._is_pass(outcome):
            return None
        if phase == VerifyPhase.TARGETED:
            return VerifyPhase.IMPACTED_SURFACE.value
        if phase == VerifyPhase.IMPACTED_SURFACE:
            return VerifyPhase.BROAD_SMOKE.value
        return None

    @staticmethod
    def _is_pass(outcome: str) -> bool:
        return outcome.strip().lower() in {"pass", "passed"}

    @staticmethod
    def _is_fail(outcome: str) -> bool:
        return outcome.strip().lower() in {"fail", "failed"}

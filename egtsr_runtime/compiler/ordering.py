from __future__ import annotations

from egtsr_runtime.enums import ObligationStatus

_STATUS_ORDER = {
    ObligationStatus.OPEN: 0,
    ObligationStatus.LOCALIZED: 1,
    ObligationStatus.ADDRESSED: 2,
    ObligationStatus.BLOCKED: 3,
}


def sort_obligations(obligations: list) -> list:
    """Sort obligations with deterministic rules."""

    return sorted(obligations, key=_sort_key)



def _sort_key(obligation: object) -> tuple:
    status = getattr(obligation, "status", None)
    created_at = getattr(obligation, "created_at", "") or ""
    obligation_id = getattr(obligation, "id", "") or ""
    priority = getattr(obligation, "priority", 0)
    return (
        0 if status == ObligationStatus.REOPENED else 1,
        -priority,
        _STATUS_ORDER.get(status, 99),
        created_at,
        obligation_id,
    )

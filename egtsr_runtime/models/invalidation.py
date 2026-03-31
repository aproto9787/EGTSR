from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from egtsr_runtime.enums import InvalidationStatus


@dataclass(slots=True)
class InvalidationTicket:
    id: str
    session_id: str
    subject_type: str
    subject_id: str
    trigger_kind: str
    trigger_ref: str | None = None
    status: InvalidationStatus = InvalidationStatus.LIVE
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

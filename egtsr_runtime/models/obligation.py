from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from egtsr_runtime.enums import ObligationStatus


@dataclass(slots=True)
class Obligation:
    id: str
    session_id: str
    source: str
    statement: str
    priority: int = 50
    status: ObligationStatus = ObligationStatus.OPEN
    acceptance_check: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AttemptFamily:
    id: str
    session_id: str
    obligation_id: str | None
    signature: str
    touched_scope: list[Any] = field(default_factory=list)
    fail_count: int = 1
    last_outcome: str = ""
    summary: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

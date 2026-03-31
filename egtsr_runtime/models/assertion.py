from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from egtsr_runtime.enums import AssertionStatus


@dataclass(slots=True)
class Assertion:
    id: str
    session_id: str
    obligation_id: str | None
    statement: str
    scope_kind: str | None = None
    scope_ref: str | None = None
    status: AssertionStatus = AssertionStatus.SPECULATIVE
    confidence: float = 0.5
    evidence_ids: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

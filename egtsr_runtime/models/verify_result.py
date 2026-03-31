from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from egtsr_runtime.enums import VerifyPhase


@dataclass(slots=True)
class VerifyResult:
    id: str
    session_id: str
    phase: VerifyPhase
    outcome: str
    affected_obligation_ids: list[str] = field(default_factory=list)
    excerpt: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

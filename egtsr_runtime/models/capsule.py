from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from egtsr_runtime.enums import VerifyPhase


@dataclass(slots=True)
class Capsule:
    id: str
    session_id: str
    phase: VerifyPhase
    frontier_hash: str
    content: str
    token_count: int
    audit_pass: bool
    audit_report: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

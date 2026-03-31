from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class DecisionCompilerInput:
    session_id: str
    token_budget: int
    open_obligations: list
    evidence: list
    assertions: list
    invalidation_tickets: list
    attempt_families: list


@dataclass(slots=True)
class ObligationBlock:
    obligation_id: str
    priority: int
    title: str
    state: str
    positive_items: list[str] = field(default_factory=list)
    negative_items: list[str] = field(default_factory=list)
    uncertainty_items: list[str] = field(default_factory=list)
    suggested_next_check: str = ""


@dataclass(slots=True)
class DecisionCapsuleV0:
    phase: str = "decision"
    header_obligations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    obligation_blocks: list[ObligationBlock] = field(default_factory=list)
    next_checks: list[str] = field(default_factory=list)
    token_estimate: int = 0
    audit_inputs: dict = field(default_factory=dict)
    rendered_text: str = ""

"""Schema for comparing legacy vs new compile results (shadow-diff)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class CompileSnapshot:
    """Captures one compile run's key outputs for diff comparison."""
    path_label: str  # "legacy" or "incremental"
    rendered_text: str = ""
    token_estimate: int = 0
    obligation_count: int = 0
    block_count: int = 0
    audit_passed: bool = False
    hard_fail_reasons: list[str] = field(default_factory=list)
    blocking_reasons: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CompileDiffResult:
    """Result of comparing two compile snapshots."""
    legacy: CompileSnapshot
    candidate: CompileSnapshot
    token_delta: int = 0
    audit_match: bool = False
    block_count_match: bool = False
    hard_fail_match: bool = False
    rendered_text_identical: bool = False

    def compute(self) -> None:
        """Populate derived diff fields from the two snapshots."""
        self.token_delta = self.candidate.token_estimate - self.legacy.token_estimate
        self.audit_match = self.legacy.audit_passed == self.candidate.audit_passed
        self.block_count_match = self.legacy.block_count == self.candidate.block_count
        self.hard_fail_match = self.legacy.hard_fail_reasons == self.candidate.hard_fail_reasons
        self.rendered_text_identical = self.legacy.rendered_text == self.candidate.rendered_text


def snapshot_from_capsule(capsule, audit, *, label: str) -> CompileSnapshot:
    """Build a CompileSnapshot from a DecisionCapsule + AuditResult."""
    return CompileSnapshot(
        path_label=label,
        rendered_text=capsule.rendered_text,
        token_estimate=capsule.token_estimate,
        obligation_count=len(capsule.obligation_blocks),
        block_count=len(capsule.obligation_blocks),
        audit_passed=audit.passed,
        hard_fail_reasons=list(audit.hard_fail_reasons) if hasattr(audit, "hard_fail_reasons") else [],
        blocking_reasons=list(audit.blocking_reasons) if hasattr(audit, "blocking_reasons") else [],
    )

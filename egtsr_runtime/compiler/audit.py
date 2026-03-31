from __future__ import annotations

from dataclasses import dataclass, field

from egtsr_runtime.compiler.decision_models import DecisionCapsuleV0


@dataclass(slots=True)
class CapsuleAuditReport:
    passed: bool = True
    hard_fail_reasons: list[str] = field(default_factory=list)
    soft_warnings: list[str] = field(default_factory=list)
    rendered_obligation_ids: list[str] = field(default_factory=list)
    open_obligation_ids: list[str] = field(default_factory=list)
    stale_evidence_ids_seen: list[str] = field(default_factory=list)
    unsupported_confirmed_assertion_ids: list[str] = field(default_factory=list)
    token_estimate: int = 0
    budget: int = 0


class CapsuleAuditEngine:
    def audit(self, capsule: DecisionCapsuleV0) -> CapsuleAuditReport:
        """Audit compiled capsule for hard-fail conditions."""

        audit_inputs = capsule.audit_inputs or {}
        rendered_obligation_ids = list(
            audit_inputs.get(
                "rendered_obligation_ids",
                [block.obligation_id for block in capsule.obligation_blocks],
            )
        )
        open_obligation_ids = list(audit_inputs.get("open_obligation_ids", []))
        stale_evidence_ids_seen = list(audit_inputs.get("stale_evidence_ids_seen", []))
        unsupported_confirmed_assertion_ids = list(
            audit_inputs.get("unsupported_confirmed_assertion_ids", [])
        )
        budget = int(audit_inputs.get("budget", 0) or 0)

        report = CapsuleAuditReport(
            rendered_obligation_ids=rendered_obligation_ids,
            open_obligation_ids=open_obligation_ids,
            stale_evidence_ids_seen=stale_evidence_ids_seen,
            unsupported_confirmed_assertion_ids=unsupported_confirmed_assertion_ids,
            token_estimate=capsule.token_estimate,
            budget=budget,
        )

        missing_obligation_ids = [
            obligation_id
            for obligation_id in open_obligation_ids
            if obligation_id not in set(rendered_obligation_ids)
        ]
        if missing_obligation_ids:
            report.hard_fail_reasons.append(
                f"Omission: missing rendered obligations: {', '.join(missing_obligation_ids)}"
            )
        if stale_evidence_ids_seen:
            report.hard_fail_reasons.append(
                f"Stale evidence leak: {', '.join(stale_evidence_ids_seen)}"
            )
        if unsupported_confirmed_assertion_ids:
            report.hard_fail_reasons.append(
                "Unsupported confirmed assertions: "
                + ", ".join(unsupported_confirmed_assertion_ids)
            )
        if budget and capsule.token_estimate > budget:
            report.soft_warnings.append(
                f"Token estimate exceeds budget: {capsule.token_estimate} > {budget}"
            )

        report.passed = not report.hard_fail_reasons
        return report

from __future__ import annotations

from egtsr_runtime.enums import AssertionStatus, InvalidationStatus, ObligationStatus

from egtsr_runtime.compiler.decision_models import DecisionCapsuleV0, DecisionCompilerInput
from egtsr_runtime.compiler.next_checks import derive_next_check
from egtsr_runtime.compiler.ordering import sort_obligations
from egtsr_runtime.compiler.pools import (
    build_obligation_pools,
    has_recent_failed_family,
    has_unresolved_stale_ticket,
)
from egtsr_runtime.compiler.renderer import render_capsule
from egtsr_runtime.compiler.token_estimator import estimate_tokens, trim_to_budget


class DecisionCapsuleCompiler:
    def compile(self, data: DecisionCompilerInput) -> DecisionCapsuleV0:
        """Compile decision capsule v0."""

        sorted_obligations = sort_obligations(data.open_obligations)
        header_obligations = [obligation.id for obligation in sorted_obligations]
        warnings = self._build_warnings(sorted_obligations, data.invalidation_tickets)
        stale_evidence_ids_seen = sorted(
            ticket.subject_id
            for ticket in data.invalidation_tickets
            if ticket.status == InvalidationStatus.LIVE and ticket.subject_type == "evidence"
        )
        unsupported_confirmed_assertion_ids = self._unsupported_confirmed_assertion_ids(data.assertions)

        obligation_blocks = []
        next_checks = []
        assertions_by_obligation = {}
        for assertion in data.assertions:
            if assertion.obligation_id is None:
                continue
            assertions_by_obligation.setdefault(assertion.obligation_id, []).append(assertion)

        for obligation in sorted_obligations:
            block = build_obligation_pools(
                obligation=obligation,
                evidence=data.evidence,
                assertions=data.assertions,
                invalidation_tickets=data.invalidation_tickets,
                attempt_families=data.attempt_families,
            )
            next_check = derive_next_check(
                obligation=obligation,
                positive=block.positive_items,
                negative=block.negative_items,
                uncertainty=block.uncertainty_items,
                has_recent_failed_family=has_recent_failed_family(obligation.id, data.attempt_families),
                has_unresolved_stale_ticket=has_unresolved_stale_ticket(
                    obligation.id,
                    assertions_by_obligation.get(obligation.id, []),
                    data.invalidation_tickets,
                ),
            )
            block.suggested_next_check = next_check
            obligation_blocks.append(block)
            next_checks.append(f"{obligation.id}: {next_check}")

        live_stale_assertion_ids = sorted(
            ticket.subject_id
            for ticket in data.invalidation_tickets
            if ticket.status == InvalidationStatus.LIVE and ticket.subject_type == "assertion"
        )
        live_reopened_obligation_ids = [
            obligation.id
            for obligation in sorted_obligations
            if obligation.status == ObligationStatus.REOPENED
        ]

        capsule = DecisionCapsuleV0(
            header_obligations=header_obligations,
            warnings=warnings,
            obligation_blocks=obligation_blocks,
            next_checks=next_checks,
            audit_inputs={
                "session_id": data.session_id,
                "budget": data.token_budget,
                "open_obligation_ids": header_obligations,
                "rendered_obligation_ids": [block.obligation_id for block in obligation_blocks],
                "stale_evidence_ids_seen": stale_evidence_ids_seen,
                "unsupported_confirmed_assertion_ids": unsupported_confirmed_assertion_ids,
                "live_stale_ticket_ids": [
                    ticket.id
                    for ticket in sorted(data.invalidation_tickets, key=lambda item: (item.created_at or "", item.id))
                    if ticket.status == InvalidationStatus.LIVE
                ],
                "live_stale_evidence_ids": stale_evidence_ids_seen,
                "live_stale_assertion_ids": live_stale_assertion_ids,
                "live_reopened_obligation_ids": live_reopened_obligation_ids,
                "reopened_obligation_ids": live_reopened_obligation_ids,
            },
        )
        capsule.rendered_text = render_capsule(capsule)
        capsule.token_estimate = estimate_tokens(capsule.rendered_text)

        if capsule.token_estimate > data.token_budget:
            capsule = trim_to_budget(capsule, data.token_budget)

        capsule.rendered_text = render_capsule(capsule)
        capsule.token_estimate = estimate_tokens(capsule.rendered_text)
        return capsule

    def _unsupported_confirmed_assertion_ids(self, assertions: list) -> list[str]:
        assertions_by_obligation: dict[str, list] = {}
        for assertion in assertions:
            if assertion.obligation_id is None:
                continue
            assertions_by_obligation.setdefault(assertion.obligation_id, []).append(assertion)

        unsupported_ids: list[str] = []
        for obligation_id, obligation_assertions in assertions_by_obligation.items():
            del obligation_id
            supported_exists = any(item.status == AssertionStatus.SUPPORTED for item in obligation_assertions)
            if supported_exists:
                continue
            unsupported_ids.extend(
                item.id for item in obligation_assertions if item.status == AssertionStatus.CONFIRMED
            )
        return sorted(unsupported_ids)

    def _build_warnings(self, obligations: list, invalidation_tickets: list) -> list[str]:
        warnings: list[str] = []
        for obligation in obligations:
            if obligation.status == ObligationStatus.REOPENED:
                warnings.append(f"Reopened obligation: {obligation.id}")
        for ticket in sorted(invalidation_tickets, key=lambda item: (item.created_at or "", item.id)):
            if ticket.status == InvalidationStatus.LIVE:
                warnings.append(f"Live stale ticket: {ticket.subject_type}:{ticket.subject_id}")
        return warnings

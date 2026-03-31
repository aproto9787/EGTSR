from __future__ import annotations

from egtsr_runtime.enums import AssertionStatus, InvalidationStatus
from egtsr_runtime.models import AttemptFamily, InvalidationTicket, Obligation

from egtsr_runtime.compiler.decision_models import ObligationBlock

NO_NEGATIVE_PLACEHOLDER = "[No negative evidence — verify before proceeding]"
NO_LIVE_EVIDENCE_PLACEHOLDER = "[No live evidence — READ REQUIRED]"



def build_obligation_block(
    obligation: Obligation,
    obligation_assertions: list,
    evidence: list,
    invalidation_tickets: list,
    attempt_families: list,
) -> ObligationBlock:
    """Build evidence pools from (possibly pre-sliced) data.

    ``obligation_assertions`` must already be filtered to this obligation
    and exclude stale assertions.  ``evidence``, ``invalidation_tickets``,
    and ``attempt_families`` may be a broader pool — the function filters
    internally per assertion/evidence/obligation ID.
    """

    evidence_by_id = {item.id: item for item in evidence}
    supported_exists = any(item.status == AssertionStatus.SUPPORTED for item in obligation_assertions)

    positive_items: list[str] = []
    negative_items: list[str] = []
    uncertainty_items: list[str] = []
    live_evidence_seen = False

    for assertion in sorted(obligation_assertions, key=_assertion_sort_key):
        if assertion.status == AssertionStatus.CONFIRMED and not supported_exists:
            continue
        linked_evidence = _live_evidence_for_assertion(assertion, evidence_by_id, invalidation_tickets)
        if linked_evidence:
            live_evidence_seen = True

        if assertion.status == AssertionStatus.SPECULATIVE:
            item = _format_uncertainty_item(assertion, linked_evidence)
            _append_unique(uncertainty_items, item)
            continue

        for evidence_item in linked_evidence:
            if assertion.status in {AssertionStatus.SUPPORTED, AssertionStatus.CONFIRMED}:
                if evidence_item.polarity == "positive":
                    _append_unique(positive_items, _format_evidence_item(assertion.statement, evidence_item))
            elif assertion.status == AssertionStatus.REFUTED and evidence_item.polarity == "negative":
                _append_unique(negative_items, _format_evidence_item(assertion.statement, evidence_item))

    for family in _recent_failed_families(obligation.id, attempt_families):
        _append_unique(negative_items, _format_attempt_family_item(family))

    if not negative_items:
        negative_items.append(NO_NEGATIVE_PLACEHOLDER)
    if not live_evidence_seen:
        uncertainty_items.append(NO_LIVE_EVIDENCE_PLACEHOLDER)

    return ObligationBlock(
        obligation_id=obligation.id,
        priority=obligation.priority,
        title=obligation.statement,
        state=obligation.status.value,
        positive_items=positive_items,
        negative_items=negative_items,
        uncertainty_items=uncertainty_items,
    )


def build_obligation_pools(
    obligation: Obligation,
    evidence: list,
    assertions: list,
    invalidation_tickets: list,
    attempt_families: list,
) -> ObligationBlock:
    """Build evidence pools for a single obligation (legacy wrapper).

    Filters session-wide ``assertions`` to the given obligation and
    delegates to :func:`build_obligation_block`.
    """

    obligation_assertions = [
        item for item in assertions if item.obligation_id == obligation.id and item.status != AssertionStatus.STALE
    ]
    return build_obligation_block(
        obligation=obligation,
        obligation_assertions=obligation_assertions,
        evidence=evidence,
        invalidation_tickets=invalidation_tickets,
        attempt_families=attempt_families,
    )



def has_recent_failed_family(obligation_id: str, attempt_families: list) -> bool:
    return any(True for _ in _recent_failed_families(obligation_id, attempt_families))



def has_unresolved_stale_ticket(obligation_id: str, assertions: list, invalidation_tickets: list) -> bool:
    assertion_ids = {item.id for item in assertions if item.obligation_id == obligation_id}
    for ticket in invalidation_tickets:
        if ticket.status != InvalidationStatus.LIVE:
            continue
        if ticket.subject_type == "obligation" and ticket.subject_id == obligation_id:
            return True
        if ticket.subject_type == "assertion" and ticket.subject_id in assertion_ids:
            return True
    return False



def _live_evidence_for_assertion(assertion: object, evidence_by_id: dict, invalidation_tickets: list) -> list:
    items = []
    for evidence_id in assertion.evidence_ids:
        evidence_item = evidence_by_id.get(evidence_id)
        if evidence_item is None:
            continue
        if _is_invalidated(evidence_item.id, assertion.id, invalidation_tickets):
            continue
        items.append(evidence_item)
    return sorted(items, key=_evidence_sort_key)



def _is_invalidated(evidence_id: str, assertion_id: str, invalidation_tickets: list[InvalidationTicket]) -> bool:
    for ticket in invalidation_tickets:
        if ticket.status != InvalidationStatus.LIVE:
            continue
        if ticket.subject_type == "evidence" and ticket.subject_id == evidence_id:
            return True
        if ticket.subject_type == "assertion" and ticket.subject_id == assertion_id:
            return True
    return False



def _recent_failed_families(obligation_id: str, attempt_families: list) -> list[AttemptFamily]:
    failed_families = []
    for family in attempt_families:
        if family.obligation_id != obligation_id:
            continue
        outcome = (family.last_outcome or "").lower()
        if "fail" not in outcome and family.fail_count <= 0:
            continue
        failed_families.append(family)
    return sorted(
        failed_families,
        key=lambda item: (
            item.updated_at or "",
            item.created_at or "",
            item.id,
        ),
        reverse=True,
    )



def _format_evidence_item(statement: str, evidence_item: object) -> str:
    excerpt = (getattr(evidence_item, "excerpt", None) or "").strip()
    source = (getattr(evidence_item, "path", None) or getattr(evidence_item, "scope_ref", None) or evidence_item.id)
    if excerpt and excerpt != statement:
        return f"{statement} | {excerpt} [{source}]"
    return f"{statement} [{source}]"



def _format_uncertainty_item(assertion: object, linked_evidence: list) -> str:
    if linked_evidence:
        return _format_evidence_item(assertion.statement, linked_evidence[0])
    return assertion.statement



def _format_attempt_family_item(family: AttemptFamily) -> str:
    summary = (family.summary or family.signature).strip() or family.id
    return f"Failed attempts: {summary} (count={family.fail_count})"



def _assertion_sort_key(assertion: object) -> tuple:
    return (assertion.created_at or "", assertion.id)



def _evidence_sort_key(evidence_item: object) -> tuple:
    return (evidence_item.created_at or "", evidence_item.id)



def _append_unique(items: list[str], value: str) -> None:
    if value not in items:
        items.append(value)

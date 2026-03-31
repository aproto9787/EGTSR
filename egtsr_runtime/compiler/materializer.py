"""Materializer — load targeted data slices for dirty obligations.

Instead of scanning all five entity tables for the entire session,
the materializer fetches only the rows needed for a given set of
obligation IDs using the targeted-query APIs added in Step 04.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from egtsr_runtime.models import (
    Assertion,
    AttemptFamily,
    Evidence,
    InvalidationTicket,
    Obligation,
)


@dataclass(slots=True)
class MaterializedSlice:
    """Pre-sliced data for a set of obligations."""

    obligations: list[Obligation] = field(default_factory=list)
    assertions: list[Assertion] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    invalidation_tickets: list[InvalidationTicket] = field(default_factory=list)
    attempt_families: list[AttemptFamily] = field(default_factory=list)


def materialize_for_obligations(uow, session_id: str, obligation_ids: list[str]) -> MaterializedSlice:
    """Load targeted data for the given obligation IDs.

    Queries use indexed lookups rather than session-wide scans:
    - assertions  -> list_active_by_obligation_ids (non-stale, by obligation)
    - evidence    -> list_by_ids (from assertion evidence_ids)
    - tickets     -> list_live_for_assertions + list_live_for_obligations + list_live_for_evidence_ids
    - families    -> list_recent_failures_by_obligation_ids
    """
    if not obligation_ids:
        return MaterializedSlice()

    obligations = uow.obligations.list_by_ids_ordered(session_id, obligation_ids)
    assertions = uow.assertions.list_active_by_obligation_ids(obligation_ids)

    # Collect evidence IDs referenced by assertions
    evidence_id_set: set[str] = set()
    for assertion in assertions:
        evidence_id_set.update(assertion.evidence_ids)
    evidence = uow.evidence.list_by_ids(sorted(evidence_id_set)) if evidence_id_set else []

    # Invalidation tickets: union of assertion-level, obligation-level, evidence-level
    assertion_ids = [a.id for a in assertions]
    evidence_ids = [e.id for e in evidence]

    tickets: list[InvalidationTicket] = []
    seen_ids: set[str] = set()

    for batch in (
        uow.invalidations.list_live_for_assertions(assertion_ids),
        uow.invalidations.list_live_for_obligations(obligation_ids),
        uow.invalidations.list_live_for_evidence_ids(evidence_ids),
    ):
        for t in batch:
            if t.id not in seen_ids:
                tickets.append(t)
                seen_ids.add(t.id)

    attempt_families = uow.attempt_families.list_recent_failures_by_obligation_ids(obligation_ids)

    return MaterializedSlice(
        obligations=obligations,
        assertions=assertions,
        evidence=evidence,
        invalidation_tickets=tickets,
        attempt_families=attempt_families,
    )

"""Render-cache hash computation for obligation-level block caching.

The hash covers all inputs that influence the rendered block so that
a cache hit guarantees the block content is still valid.
"""
from __future__ import annotations

import hashlib
import json


def compute_render_hash(
    obligation_id: str,
    obligation_status: str,
    obligation_priority: int,
    assertion_summaries: list[tuple[str, str, str]],
    evidence_summaries: list[tuple[str, str, str | None]],
    live_ticket_ids: list[str],
    failed_family_summaries: list[tuple[str, int]],
    token_budget: int,
) -> str:
    """Compute a deterministic hash over the inputs to an obligation block.

    Parameters
    ----------
    assertion_summaries:
        List of (id, status, updated_at) tuples.
    evidence_summaries:
        List of (id, polarity, scope_ref_or_path) tuples.
    live_ticket_ids:
        Sorted list of live invalidation ticket IDs relevant to this obligation.
    failed_family_summaries:
        List of (id, fail_count) tuples.
    """
    payload = {
        "obligation_id": obligation_id,
        "obligation_status": obligation_status,
        "obligation_priority": obligation_priority,
        "assertions": sorted(assertion_summaries),
        "evidence": sorted(evidence_summaries),
        "live_tickets": sorted(live_ticket_ids),
        "failed_families": sorted(failed_family_summaries),
        "token_budget": token_budget,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

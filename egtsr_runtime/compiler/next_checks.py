from __future__ import annotations

from egtsr_runtime.compiler.pools import NO_LIVE_EVIDENCE_PLACEHOLDER



def derive_next_check(
    obligation,
    positive: list[str],
    negative: list[str],
    uncertainty: list[str],
    has_recent_failed_family: bool,
    has_unresolved_stale_ticket: bool,
) -> str:
    """Derive suggested next check for an obligation."""

    del obligation, positive

    if NO_LIVE_EVIDENCE_PLACEHOLDER in uncertainty:
        return "READ_REQUIRED"
    if has_recent_failed_family:
        return "INVESTIGATE_ALT_PATH"
    if has_unresolved_stale_ticket:
        return "RECHECK_STALE"
    if uncertainty:
        return "VERIFY_UNCERTAINTY"
    if negative:
        return "ADDRESS_NEGATIVE"
    return "CONTINUE"

from enum import StrEnum


class ObligationStatus(StrEnum):
    OPEN = "open"
    LOCALIZED = "localized"
    ADDRESSED = "addressed"
    VERIFIED = "verified"
    REOPENED = "reopened"
    BLOCKED = "blocked"


class AssertionStatus(StrEnum):
    SPECULATIVE = "speculative"
    SUPPORTED = "supported"
    CONFIRMED = "confirmed"
    REFUTED = "refuted"
    STALE = "stale"


class InvalidationStatus(StrEnum):
    LIVE = "live"
    STALE = "stale"
    REVALIDATED = "revalidated"
    CLOSED = "closed"


class VerifyPhase(StrEnum):
    DECISION = "decision"
    TARGETED = "targeted"
    IMPACTED_SURFACE = "impacted_surface"
    BROAD_SMOKE = "broad_smoke"

from __future__ import annotations

from typing import Any

from egtsr_runtime.enums import AssertionStatus, InvalidationStatus, ObligationStatus, VerifyPhase
from egtsr_runtime.models import (
    Assertion,
    AttemptFamily,
    Capsule,
    Event,
    Evidence,
    InvalidationTicket,
    Obligation,
    RepoState,
    Session,
    VerifyResult,
)


def seed_db(uow, data: dict[str, Any]) -> None:
    for item in data.get("sessions", []):
        session = Session(**item)
        if uow.sessions.get(session.id) is None:
            uow.sessions.create(session)
        else:
            uow.sessions.update(session)

    for item in data.get("repo_state", []):
        uow.repo_state.upsert(
            RepoState(
                session_id=item["session_id"],
                head_hash=item.get("head_hash"),
                dirty=bool(item.get("dirty", False)),
                changed_files=list(item.get("changed_files", [])),
                last_scan_at=item["last_scan_at"],
            )
        )

    for item in data.get("obligations", []):
        uow.obligations.upsert(
            Obligation(
                id=item["id"],
                session_id=item["session_id"],
                source=item["source"],
                statement=item["statement"],
                priority=item.get("priority", 50),
                status=ObligationStatus(item["status"]),
                acceptance_check=item.get("acceptance_check"),
                metadata=dict(item.get("metadata", {})),
                created_at=item["created_at"],
                updated_at=item["updated_at"],
            )
        )

    for item in data.get("evidence", []):
        uow.evidence.create(
            Evidence(
                id=item["id"],
                session_id=item["session_id"],
                kind=item["kind"],
                source_tool=item["source_tool"],
                path=item.get("path"),
                scope_kind=item.get("scope_kind"),
                scope_ref=item.get("scope_ref"),
                file_hash=item.get("file_hash"),
                polarity=item.get("polarity", "positive"),
                excerpt=item.get("excerpt"),
                metadata=dict(item.get("metadata", {})),
                created_at=item["created_at"],
            )
        )

    for item in data.get("assertions", []):
        uow.assertions.upsert(
            Assertion(
                id=item["id"],
                session_id=item["session_id"],
                obligation_id=item.get("obligation_id"),
                statement=item["statement"],
                scope_kind=item.get("scope_kind"),
                scope_ref=item.get("scope_ref"),
                status=AssertionStatus(item["status"]),
                confidence=item.get("confidence", 0.5),
                evidence_ids=list(item.get("evidence_ids", [])),
                metadata=dict(item.get("metadata", {})),
                created_at=item["created_at"],
                updated_at=item["updated_at"],
            )
        )

    for item in data.get("invalidation_tickets", []):
        uow.invalidations.upsert(
            InvalidationTicket(
                id=item["id"],
                session_id=item["session_id"],
                subject_type=item["subject_type"],
                subject_id=item["subject_id"],
                trigger_kind=item["trigger_kind"],
                trigger_ref=item.get("trigger_ref"),
                status=InvalidationStatus(item["status"]),
                metadata=dict(item.get("metadata", {})),
                created_at=item["created_at"],
                updated_at=item["updated_at"],
            )
        )

    for item in data.get("attempt_families", []):
        uow.attempt_families.upsert(
            AttemptFamily(
                id=item["id"],
                session_id=item["session_id"],
                obligation_id=item.get("obligation_id"),
                signature=item["signature"],
                touched_scope=list(item.get("touched_scope", [])),
                fail_count=item.get("fail_count", 1),
                last_outcome=item["last_outcome"],
                summary=item.get("summary"),
                metadata=dict(item.get("metadata", {})),
                created_at=item["created_at"],
                updated_at=item["updated_at"],
            )
        )

    for item in data.get("verify_results", []):
        uow.verify_results.create(
            VerifyResult(
                id=item["id"],
                session_id=item["session_id"],
                phase=VerifyPhase(item["phase"]),
                outcome=item["outcome"],
                affected_obligation_ids=list(item.get("affected_obligation_ids", [])),
                excerpt=item.get("excerpt"),
                metadata=dict(item.get("metadata", {})),
                created_at=item["created_at"],
            )
        )

    for item in data.get("capsules", []):
        uow.capsules.create(
            Capsule(
                id=item["id"],
                session_id=item["session_id"],
                phase=VerifyPhase(item["phase"]),
                frontier_hash=item["frontier_hash"],
                content=item["content"],
                token_count=item["token_count"],
                audit_pass=bool(item["audit_pass"]),
                audit_report=dict(item.get("audit_report", {})),
                created_at=item["created_at"],
            )
        )

    for item in data.get("events", []):
        uow.events.create(
            Event(
                id=item["id"],
                session_id=item["session_id"],
                event_type=item["event_type"],
                payload=dict(item.get("payload", {})),
                created_at=item["created_at"],
            )
        )

from __future__ import annotations

import hashlib
import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from egtsr_runtime.models import AttemptFamily, Event


class AttemptFamilyService:
    def __init__(self, uow):
        self._uow = uow

    def register_failure(
        self,
        session_id: str,
        obligation_id: str | None,
        touched_files: list[str],
        outcome: str,
        excerpt: str = "",
    ) -> AttemptFamily:
        """Register a failure attempt, merging into existing family if signature matches."""

        scope = sorted(touched_files)
        signature = self.compute_signature(obligation_id, scope)
        existing = self._uow.attempt_families.get_by_signature(session_id, signature)
        now = datetime.now(timezone.utc).isoformat()
        summary = self._build_summary(outcome=outcome, touched_files=scope, excerpt=excerpt)

        if existing is None:
            family = AttemptFamily(
                id=uuid.uuid4().hex,
                session_id=session_id,
                obligation_id=obligation_id,
                signature=signature,
                touched_scope=scope,
                fail_count=1,
                last_outcome=outcome,
                summary=summary,
                metadata=self._build_metadata(excerpt, scope),
                created_at=now,
                updated_at=now,
            )
        else:
            metadata = dict(existing.metadata)
            metadata.update(self._build_metadata(excerpt, scope))
            family = AttemptFamily(
                id=existing.id,
                session_id=existing.session_id,
                obligation_id=existing.obligation_id if existing.obligation_id is not None else obligation_id,
                signature=existing.signature,
                touched_scope=scope,
                fail_count=existing.fail_count + 1,
                last_outcome=outcome,
                summary=summary,
                metadata=metadata,
                created_at=existing.created_at,
                updated_at=now,
            )

        self._uow.attempt_families.upsert(family)
        self._uow.events.create(
            Event(
                id=uuid.uuid4().hex,
                session_id=session_id,
                event_type="attempt_family.registered",
                payload={
                    "attempt_family_id": family.id,
                    "obligation_id": family.obligation_id,
                    "signature": family.signature,
                    "fail_count": family.fail_count,
                },
                created_at=now,
            )
        )
        return family

    def export_families(self, session_id: str) -> list[dict]:
        """Export all attempt families for session as list of dicts."""

        return [asdict(family) for family in self._uow.attempt_families.list_for_session(session_id)]

    @staticmethod
    def compute_signature(obligation_id: str | None, touched_files: list[str]) -> str:
        payload = f"{obligation_id or ''}:{':'.join(sorted(touched_files))}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _build_summary(outcome: str, touched_files: list[str], excerpt: str) -> str:
        excerpt_text = excerpt.strip()
        if excerpt_text:
            return excerpt_text
        if touched_files:
            return f"{outcome}: {', '.join(touched_files)}"
        return outcome

    @staticmethod
    def _build_metadata(excerpt: str, touched_files: list[str]) -> dict[str, object]:
        return {
            "last_excerpt": excerpt,
            "touched_files": list(touched_files),
        }

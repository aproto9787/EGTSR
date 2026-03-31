from __future__ import annotations

import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from egtsr_runtime.enums import AssertionStatus, InvalidationStatus, ObligationStatus
from egtsr_runtime.models import InvalidationTicket


@dataclass(slots=True)
class InvalidationResult:
    invalidation_ticket_ids: list[str] = field(default_factory=list)
    stale_assertion_ids: list[str] = field(default_factory=list)
    reopened_obligation_ids: list[str] = field(default_factory=list)


class FileTouchInvalidationService:
    def __init__(self, uow):
        self._uow = uow

    def apply(self, session_id: str, changed_files: list[str]) -> InvalidationResult:
        """Apply file-touch invalidation v0."""
        normalized_changed_files = self._normalize_changed_files(changed_files)
        if not normalized_changed_files:
            return InvalidationResult()

        impacted_assertions = self._find_impacted_assertions(session_id, normalized_changed_files)
        if not impacted_assertions:
            return InvalidationResult()

        result = InvalidationResult()
        evidence_by_id = self._evidence_by_id(session_id)
        stale_assertion_id_set: set[str] = set()

        for assertion in impacted_assertions:
            now = self._now()
            trigger_ref = self._find_trigger_ref(assertion, normalized_changed_files, evidence_by_id)
            ticket = InvalidationTicket(
                id=uuid.uuid4().hex,
                session_id=session_id,
                subject_type="assertion",
                subject_id=assertion.id,
                trigger_kind="file_touch",
                trigger_ref=trigger_ref,
                status=InvalidationStatus.LIVE,
                created_at=now,
                updated_at=now,
            )
            self._uow.invalidations.upsert(ticket)
            assertion.status = AssertionStatus.STALE
            assertion.updated_at = now
            self._uow.assertions.upsert(assertion)
            result.invalidation_ticket_ids.append(ticket.id)
            result.stale_assertion_ids.append(assertion.id)
            stale_assertion_id_set.add(assertion.id)

        reopen_candidates = self._find_reopen_candidates(session_id, result.stale_assertion_ids)
        stale_assertions_by_obligation = {
            assertion.obligation_id: assertion
            for assertion in impacted_assertions
            if assertion.id in stale_assertion_id_set and assertion.obligation_id
        }
        for obligation in reopen_candidates:
            now = self._now()
            related_assertion = stale_assertions_by_obligation.get(obligation.id)
            trigger_ref = None
            if related_assertion is not None:
                trigger_ref = self._find_trigger_ref(related_assertion, normalized_changed_files, evidence_by_id)
            ticket = InvalidationTicket(
                id=uuid.uuid4().hex,
                session_id=session_id,
                subject_type="obligation",
                subject_id=obligation.id,
                trigger_kind="file_touch",
                trigger_ref=trigger_ref,
                status=InvalidationStatus.LIVE,
                created_at=now,
                updated_at=now,
            )
            self._uow.invalidations.upsert(ticket)
            self._uow.obligations.mark_status(obligation.id, ObligationStatus.REOPENED.value)
            result.invalidation_ticket_ids.append(ticket.id)
            result.reopened_obligation_ids.append(obligation.id)

        return result

    def _find_impacted_assertions(self, session_id: str, changed_files: list[str]) -> list:
        """Find assertions impacted by changed files."""
        all_assertions = self._uow.assertions.list_for_session(session_id)
        evidence_by_id = self._evidence_by_id(session_id)
        changed_set = set(changed_files)
        impacted = []
        for assertion in all_assertions:
            if assertion.status == AssertionStatus.STALE:
                continue
            if self._matches_changed_file(assertion.scope_ref, changed_set):
                impacted.append(assertion)
                continue
            if self._assertion_has_matching_evidence(assertion, evidence_by_id, changed_set):
                impacted.append(assertion)
        return impacted

    def _find_reopen_candidates(self, session_id: str, stale_assertion_ids: list[str]) -> list:
        """Find VERIFIED obligations linked to stale assertions for reopening."""
        obligations = self._uow.obligations.list_for_session(session_id)
        stale_set = set(stale_assertion_ids)
        all_assertions = self._uow.assertions.list_for_session(session_id)

        impacted_obligation_ids = set()
        for assertion in all_assertions:
            if assertion.id in stale_set and assertion.obligation_id:
                impacted_obligation_ids.add(assertion.obligation_id)

        candidates = []
        for obligation in obligations:
            if obligation.id in impacted_obligation_ids and obligation.status == ObligationStatus.VERIFIED:
                candidates.append(obligation)
        return candidates

    def _evidence_by_id(self, session_id: str) -> dict[str, object]:
        return {item.id: item for item in self._uow.evidence.list_for_session(session_id)}

    def _assertion_has_matching_evidence(self, assertion, evidence_by_id: dict[str, object], changed_set: set[str]) -> bool:
        for evidence_id in assertion.evidence_ids:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                continue
            if self._matches_changed_file(getattr(evidence, "path", None), changed_set):
                return True
            if self._matches_changed_file(getattr(evidence, "scope_ref", None), changed_set):
                return True
        return False

    def _find_trigger_ref(self, assertion, changed_files: list[str], evidence_by_id: dict[str, object]) -> str | None:
        changed_set = set(changed_files)
        normalized_scope_ref = self._normalize_path(assertion.scope_ref)
        if normalized_scope_ref in changed_set:
            return normalized_scope_ref
        for evidence_id in assertion.evidence_ids:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                continue
            for candidate in (getattr(evidence, "path", None), getattr(evidence, "scope_ref", None)):
                normalized_candidate = self._normalize_path(candidate)
                if normalized_candidate in changed_set:
                    return normalized_candidate
        return changed_files[0] if changed_files else None

    @staticmethod
    def _matches_changed_file(path: str | None, changed_set: set[str]) -> bool:
        normalized_path = FileTouchInvalidationService._normalize_path(path)
        return bool(normalized_path) and normalized_path in changed_set

    @staticmethod
    def _normalize_changed_files(changed_files: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for changed_file in changed_files:
            cleaned = FileTouchInvalidationService._normalize_path(changed_file)
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                normalized.append(cleaned)
        return normalized

    @staticmethod
    def _normalize_path(path: str | None) -> str:
        if path is None:
            return ""
        cleaned = str(path).strip()
        if not cleaned:
            return ""
        return os.path.normpath(cleaned)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

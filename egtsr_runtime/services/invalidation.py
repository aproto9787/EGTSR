from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from egtsr_runtime.enums import AssertionStatus, InvalidationStatus, ObligationStatus
from egtsr_runtime.models import InvalidationTicket
from egtsr_runtime.utils.paths import normalize_path as _shared_normalize_path


@dataclass(slots=True)
class InvalidationResult:
    invalidation_ticket_ids: list[str] = field(default_factory=list)
    stale_assertion_ids: list[str] = field(default_factory=list)
    reopened_obligation_ids: list[str] = field(default_factory=list)


class FileTouchInvalidationService:
    def __init__(self, uow, *, enable_reverse_index: bool = False):
        self._uow = uow
        self._enable_reverse_index = enable_reverse_index

    def apply(self, session_id: str, changed_files: list[str]) -> InvalidationResult:
        """Apply file-touch invalidation.

        When ``enable_reverse_index`` is True, uses projection tables
        (path_subject_index + assertion_evidence_links) for bounded
        lookups instead of session-wide scans.
        """
        normalized_changed_files = self._normalize_changed_files(changed_files)
        if not normalized_changed_files:
            return InvalidationResult()

        if self._enable_reverse_index:
            return self._apply_reverse_index(session_id, normalized_changed_files)
        return self._apply_legacy(session_id, normalized_changed_files)

    # ------------------------------------------------------------------
    # Legacy path (session-wide scan)
    # ------------------------------------------------------------------

    def _apply_legacy(self, session_id: str, normalized_changed_files: list[str]) -> InvalidationResult:
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

    # ------------------------------------------------------------------
    # Reverse-index path (bounded queries only)
    # ------------------------------------------------------------------

    def _apply_reverse_index(self, session_id: str, normalized_changed_files: list[str]) -> InvalidationResult:
        """Reverse-index invalidation: no session-wide scans."""
        # 1. Find impacted assertion IDs via path_subject_index
        impacted_assertion_ids = set(
            self._uow.path_subject_index.list_subject_ids_for_paths(
                session_id, normalized_changed_files, "assertion"
            )
        )

        # 2. Find impacted evidence IDs → expand to assertion IDs via links
        impacted_evidence_ids = self._uow.path_subject_index.list_subject_ids_for_paths(
            session_id, normalized_changed_files, "evidence"
        )
        if impacted_evidence_ids:
            linked_assertion_ids = self._uow.assertion_evidence_links.list_assertion_ids_for_evidences(
                impacted_evidence_ids
            )
            impacted_assertion_ids.update(linked_assertion_ids)

        if not impacted_assertion_ids:
            return InvalidationResult()

        # 3. Fetch impacted assertions (targeted, no session scan)
        all_impacted = self._uow.assertions.list_by_ids(list(impacted_assertion_ids))
        active_assertions = [a for a in all_impacted if a.status != AssertionStatus.STALE]

        if not active_assertions:
            return InvalidationResult()

        # 4. Build targeted evidence map for trigger_ref calculation
        needed_evidence_ids: set[str] = set()
        for assertion in active_assertions:
            needed_evidence_ids.update(assertion.evidence_ids)
        evidence_items = self._uow.evidence.list_by_ids(list(needed_evidence_ids))
        evidence_by_id = {e.id: e for e in evidence_items}

        result = InvalidationResult()
        now = self._now()

        # 5. Create assertion invalidation tickets (bulk)
        assertion_tickets: list[InvalidationTicket] = []
        stale_ids: list[str] = []
        for assertion in active_assertions:
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
            assertion_tickets.append(ticket)
            stale_ids.append(assertion.id)
            result.invalidation_ticket_ids.append(ticket.id)
            result.stale_assertion_ids.append(assertion.id)

        self._uow.invalidations.bulk_upsert(assertion_tickets)
        self._uow.assertions.bulk_mark_stale(stale_ids, now)

        # 6. Find reopen candidates (targeted — no session scan)
        impacted_obligation_ids = {a.obligation_id for a in active_assertions if a.obligation_id}

        if impacted_obligation_ids:
            obligations = self._uow.obligations.list_by_ids_ordered(
                session_id, list(impacted_obligation_ids)
            )
            reopen_candidates = [o for o in obligations if o.status == ObligationStatus.VERIFIED]

            stale_assertions_by_obligation = {
                a.obligation_id: a for a in active_assertions if a.obligation_id
            }

            obligation_tickets: list[InvalidationTicket] = []
            reopen_ids: list[str] = []
            for obligation in reopen_candidates:
                related_assertion = stale_assertions_by_obligation.get(obligation.id)
                trigger_ref = None
                if related_assertion:
                    trigger_ref = self._find_trigger_ref(
                        related_assertion, normalized_changed_files, evidence_by_id
                    )
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
                obligation_tickets.append(ticket)
                reopen_ids.append(obligation.id)
                result.invalidation_ticket_ids.append(ticket.id)
                result.reopened_obligation_ids.append(obligation.id)

            self._uow.invalidations.bulk_upsert(obligation_tickets)
            if reopen_ids:
                self._uow.obligations.bulk_mark_reopened(reopen_ids, now)

            # 7. Mark obligation frontier dirty for all impacted obligations
            from egtsr_runtime.services.projections import mark_obligation_frontier_dirty

            conn = self._uow.conn
            for obl_id in impacted_obligation_ids:
                mark_obligation_frontier_dirty(conn, obl_id, "file_touch")

        return result

    # ------------------------------------------------------------------
    # Legacy helpers (used by _apply_legacy)
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

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
        return _shared_normalize_path(path)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()

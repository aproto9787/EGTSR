from __future__ import annotations

import uuid
from datetime import datetime, timezone

from egtsr_runtime.hooks.envelopes import HookEnvelope
from egtsr_runtime.ingest import IngestResult, get_normalizer
from egtsr_runtime.models import Event
from egtsr_runtime.services import FileTouchInvalidationService
from egtsr_runtime.services.raw_archive import archive_raw_event


class PostToolUseService:
    def __init__(self, uow, raw_events_dir: str):
        self._uow = uow
        self._raw_events_dir = raw_events_dir

    def handle(self, envelope: HookEnvelope) -> IngestResult:
        """Handle PostToolUse event."""
        archive_path = archive_raw_event(self._raw_events_dir, envelope)
        normalizer = get_normalizer(envelope.tool_name or "")
        evidence_items = normalizer.normalize(envelope)
        changed_files = normalizer.changed_files(envelope)
        evidence_ids: list[str] = []

        for evidence in evidence_items:
            self._uow.evidence.create(evidence)
            evidence_ids.append(evidence.id)

        FileTouchInvalidationService(self._uow).apply(envelope.session_id, changed_files)

        self._uow.events.create(
            Event(
                id=uuid.uuid4().hex,
                session_id=envelope.session_id,
                event_type="post_tool_use.ingested",
                payload={
                    "hook_event_name": envelope.hook_event_name,
                    "tool_name": envelope.tool_name,
                    "tool_use_id": envelope.tool_use_id,
                    "evidence_ids": evidence_ids,
                    "changed_files": changed_files,
                    "raw_archive_path": archive_path,
                },
                created_at=datetime.now(timezone.utc).isoformat(),
            )
        )
        self._uow.commit()
        return IngestResult(evidence_ids=evidence_ids, changed_files=changed_files)

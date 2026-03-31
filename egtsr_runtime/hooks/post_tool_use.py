from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from egtsr_runtime.hooks.envelopes import HookEnvelope
from egtsr_runtime.ingest import IngestResult, get_normalizer
from egtsr_runtime.models import Event
from egtsr_runtime.services import FileTouchInvalidationService
from egtsr_runtime.services.raw_archive import archive_raw_event

if TYPE_CHECKING:
    from egtsr_runtime.config import RuntimeConfig


class PostToolUseService:
    def __init__(self, uow, raw_events_dir: str, config: RuntimeConfig | None = None):
        self._uow = uow
        self._raw_events_dir = raw_events_dir
        self._config = config

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

        enable_reverse_index = bool(self._config and self._config.enable_reverse_index)

        from egtsr_runtime.config import is_shadow_mode

        if self._config and is_shadow_mode(self._config) and changed_files:
            self._invalidate_shadow(envelope.session_id, changed_files)
        else:
            FileTouchInvalidationService(
                self._uow, enable_reverse_index=enable_reverse_index
            ).apply(envelope.session_id, changed_files)

        # Repo state delta update (Step 06): sync changed_files to repo_state
        if enable_reverse_index and changed_files:
            now = datetime.now(timezone.utc).isoformat()
            self._uow.repo_state.mark_dirty(envelope.session_id, changed_files, now)
            from egtsr_runtime.services.projections import on_repo_state_change

            on_repo_state_change(self._uow.conn, envelope.session_id)

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

    def _invalidate_shadow(self, session_id: str, changed_files: list[str]) -> None:
        """Shadow-mode invalidation: run legacy, log diff with reverse-index."""
        from egtsr_runtime.compat.shadow_runner import (
            ShadowInvalidationRunner,
            write_shadow_diff_report,
        )

        runner = ShadowInvalidationRunner(self._uow)
        shadow_result = runner.apply(session_id, changed_files)

        # Legacy result is already applied by the runner.
        # Write diff report for observability.
        if self._config:
            from egtsr_runtime.paths import ensure_runtime_dirs

            paths = ensure_runtime_dirs(self._config.repo_root)
            write_shadow_diff_report(
                paths.reports_dir,
                hook_name="post_tool_use",
                session_id=session_id,
                invalidation_result=shadow_result,
            )

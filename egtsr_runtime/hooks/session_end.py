from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import datetime, timezone

from egtsr_runtime.db.uow import load_snapshot, save_snapshot
from egtsr_runtime.enums import VerifyPhase
from egtsr_runtime.hooks.responses import build_allow_response
from egtsr_runtime.models import Capsule, Event, Session, SessionSnapshot
from egtsr_runtime.services import ResumeGateService, SnapshotWriter, archive_raw_event


class SessionEndService:
    def __init__(self, uow, paths, raw_events_dir: str):
        self._uow = uow
        self._paths = paths
        self._raw_events_dir = raw_events_dir
        self._resume_gate = ResumeGateService(uow)
        self._snapshot_writer = SnapshotWriter(paths)

    def handle(self, envelope) -> dict:
        """Handle SessionEnd event."""

        archive_path = archive_raw_event(self._raw_events_dir, envelope)
        now = datetime.now(timezone.utc).isoformat()

        snapshot = self._build_snapshot(envelope, now)
        save_snapshot(self._uow, snapshot)

        latest_capsule = snapshot.capsules[-1] if snapshot.capsules else None

        gate = self._load_current_gate(
            session_id=envelope.session_id,
            source=envelope.source,
            repo_dirty=bool(snapshot.repo_state and snapshot.repo_state.dirty),
        )
        self._uow.resume_gate_repo.upsert(gate)

        # JSON exports — non-authoritative, failure does not affect gate
        try:
            self._snapshot_writer.write_last_good_capsule(
                self._serialize_capsule(latest_capsule, envelope.session_id, now)
            )
        except Exception:
            pass
        try:
            self._snapshot_writer.write_resume_gate(gate)
        except Exception:
            pass

        self._uow.events.create(
            Event(
                id=uuid.uuid4().hex,
                session_id=envelope.session_id,
                event_type="session_end.handled",
                payload={
                    "hook_event_name": envelope.hook_event_name,
                    "source": envelope.source,
                    "snapshot_saved": True,
                    "last_good_capsule_path": self._paths.last_good_capsule_path,
                    "resume_gate_path": self._paths.resume_gate_path,
                    "raw_archive_path": archive_path,
                },
                created_at=now,
            )
        )
        self._uow.commit()

        return build_allow_response(
            envelope.hook_event_name,
            additional_context=(
                "snapshot_saved=true; "
                f"last_good_capsule={self._paths.last_good_capsule_path}; "
                f"resume_gate={self._paths.resume_gate_path}; "
                f"raw_archive={archive_path}"
            ),
        )

    def _build_snapshot(self, envelope, now: str) -> SessionSnapshot:
        current = load_snapshot(self._uow, envelope.session_id)
        if current is not None:
            session = Session(
                id=current.session.id,
                repo_root=envelope.cwd,
                branch=current.session.branch,
                head_hash=current.session.head_hash,
                status=current.session.status,
                created_at=current.session.created_at,
                updated_at=now,
            )
            return SessionSnapshot(
                session=session,
                repo_state=current.repo_state,
                capsules=current.capsules,
                events=current.events,
            )

        repo_state = self._uow.repo_state.get(envelope.session_id)
        return SessionSnapshot(
            session=Session(
                id=envelope.session_id,
                repo_root=envelope.cwd,
                branch=None,
                head_hash=repo_state.head_hash if repo_state is not None else None,
                status="active",
                created_at=now,
                updated_at=now,
            ),
            repo_state=repo_state,
            capsules=self._uow.capsules.list_for_session(envelope.session_id),
            events=self._uow.events.list_for_session(envelope.session_id),
        )

    def _load_current_gate(self, session_id: str, source: str | None, repo_dirty: bool) -> object:
        stored_gate = self._uow.resume_gate_repo.get(session_id)
        evaluated_gate = self._resume_gate.evaluate(
            session_id=session_id,
            source=source,
            repo_dirty=repo_dirty,
        )
        if stored_gate is not None and stored_gate.edit_blocked and not evaluated_gate.edit_blocked:
            return stored_gate
        return evaluated_gate

    @staticmethod
    def _serialize_capsule(capsule: Capsule | None, session_id: str, now: str) -> dict:
        if capsule is None:
            return {
                "session_id": session_id,
                "compiled_at": now,
                "phase": "decision",
                "token_estimate": 0,
                "open_obligation_ids": [],
                "blocking_rechecks": [],
                "content": "",
            }

        audit_inputs = capsule.audit_report or {}
        return {
            "session_id": capsule.session_id,
            "compiled_at": capsule.created_at,
            "phase": "decision",
            "token_estimate": capsule.token_count,
            "open_obligation_ids": audit_inputs.get("open_obligation_ids", []),
            "blocking_rechecks": audit_inputs.get("blocking_rechecks", []),
            "content": capsule.content,
        }

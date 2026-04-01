from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from egtsr_runtime.models import Event, RepoState, Session
from egtsr_runtime.paths import ensure_runtime_dirs
from egtsr_runtime.services.freshness_gate import FreshnessGateService
from egtsr_runtime.services.raw_archive import archive_raw_event
from egtsr_runtime.services.resume_gate import ResumeGateService
from egtsr_runtime.services.repo_inspector import inspect_repo
from egtsr_runtime.services.snapshot_writer import SnapshotWriter

if TYPE_CHECKING:
    from egtsr_runtime.db.uow import SqliteUnitOfWork
    from egtsr_runtime.hooks.envelopes import HookEnvelope


@dataclass(slots=True)
class SessionBootstrapResult:
    session_id: str
    repo_head: str | None
    dirty: bool
    branch: str | None
    safe_resume: bool
    additional_context: str | None
    is_new_session: bool


class SessionBootstrapService:
    def __init__(self, uow: "SqliteUnitOfWork", raw_events_dir: str):
        self._uow = uow
        self._raw_events_dir = raw_events_dir

    def load_or_create(self, envelope: "HookEnvelope") -> SessionBootstrapResult:
        """Bootstrap session from SessionStart event."""
        archive_path = archive_raw_event(self._raw_events_dir, envelope)
        now = datetime.now(timezone.utc).isoformat()

        existing_session = self._uow.sessions.get(envelope.session_id)
        is_new_session = existing_session is None

        repo_info = inspect_repo(envelope.cwd)

        if is_new_session:
            session = Session(
                id=envelope.session_id,
                repo_root=envelope.cwd,
                branch=repo_info.branch,
                head_hash=repo_info.head_hash,
                status="active",
                created_at=now,
                updated_at=now,
            )
            self._uow.sessions.create(session)
        else:
            session = Session(
                id=existing_session.id,
                repo_root=envelope.cwd,
                branch=repo_info.branch,
                head_hash=repo_info.head_hash,
                status=existing_session.status,
                created_at=existing_session.created_at,
                updated_at=now,
            )
            self._uow.sessions.update(session)

        self._uow.repo_state.upsert(
            RepoState(
                session_id=envelope.session_id,
                head_hash=repo_info.head_hash,
                dirty=repo_info.dirty,
                changed_files=[],
                last_scan_at=now,
            )
        )

        safe_resume = envelope.source in {"resume", "compact"}
        gate = ResumeGateService(self._uow).evaluate(
            session_id=envelope.session_id,
            source=envelope.source,
            repo_dirty=repo_info.dirty,
        )
        self._uow.resume_gate_repo.upsert(gate)
        try:
            SnapshotWriter(ensure_runtime_dirs(envelope.cwd)).write_resume_gate(gate)
        except Exception:
            pass  # JSON export is non-authoritative; DB is truth

        # --- Freshness frontier ---
        freshness_warning = None
        try:
            freshness_gate = FreshnessGateService(self._uow, envelope.cwd)
            # 1. 기존 frontier 먼저 조회 (새 row 삽입 전)
            prev = self._uow.freshness_repo.get_latest_by_source(
                envelope.session_id, "session_start"
            )
            # 2. 현재 상태 수집 및 저장
            frontier = freshness_gate.collect_frontier(
                envelope.session_id, "session_start"
            )
            # 3. resume 시 이전 frontier와 비교
            if not is_new_session and prev is not None:
                from egtsr_runtime.models.freshness import compute_freshness_diff

                diff = compute_freshness_diff(prev, frontier)
                if diff.has_mismatch:
                    freshness_warning = (
                        f"freshness_mismatch: "
                        f"{FreshnessGateService.describe_mismatch(diff)}"
                    )
        except Exception:
            pass  # Freshness collection failure is non-fatal at session start

        additional_context = self._build_additional_context(
            session_id=envelope.session_id,
            source=envelope.source,
            repo_info=repo_info,
            safe_resume=safe_resume,
            gate=gate,
            is_new_session=is_new_session,
            archive_path=archive_path,
            freshness_warning=freshness_warning,
        )

        self._uow.events.create(
            Event(
                id=uuid.uuid4().hex,
                session_id=envelope.session_id,
                event_type="session.bootstrap",
                payload={
                    "hook_event_name": envelope.hook_event_name,
                    "source": envelope.source,
                    "safe_resume": safe_resume,
                    "repo_head": repo_info.head_hash,
                    "dirty": repo_info.dirty,
                    "branch": repo_info.branch,
                    "resume_gate_blocked": gate.edit_blocked,
                    "required_rechecks": gate.required_rechecks,
                    "raw_archive_path": archive_path,
                    "is_new_session": is_new_session,
                },
                created_at=now,
            )
        )
        self._uow.commit()

        return SessionBootstrapResult(
            session_id=envelope.session_id,
            repo_head=repo_info.head_hash,
            dirty=repo_info.dirty,
            branch=repo_info.branch,
            safe_resume=safe_resume,
            additional_context=additional_context,
            is_new_session=is_new_session,
        )

    @staticmethod
    def _build_additional_context(
        *,
        session_id: str,
        source: str | None,
        repo_info: object,
        safe_resume: bool,
        gate: object,
        is_new_session: bool,
        archive_path: str,
        freshness_warning: str | None = None,
    ) -> str:
        ctx = (
            f"session_id={session_id}; "
            f"source={source or 'unknown'}; "
            f"safe_resume={str(safe_resume).lower()}; "
            f"resume_gate_blocked={str(bool(getattr(gate, 'edit_blocked', False))).lower()}; "
            f"required_rechecks={','.join(getattr(gate, 'required_rechecks', [])) or 'none'}; "
            f"resume_gate_reason={getattr(gate, 'reason', None) or 'none'}; "
            f"is_new_session={str(is_new_session).lower()}; "
            f"branch={getattr(repo_info, 'branch', None) or 'unknown'}; "
            f"head={getattr(repo_info, 'head_hash', None) or 'unknown'}; "
            f"dirty={str(bool(getattr(repo_info, 'dirty', False))).lower()}; "
            f"raw_archive={archive_path}"
        )
        if freshness_warning:
            ctx += f"; {freshness_warning}"
        return ctx

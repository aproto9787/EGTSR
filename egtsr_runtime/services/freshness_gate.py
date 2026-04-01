from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from egtsr_runtime.enums import InvalidationStatus, ObligationStatus
from egtsr_runtime.models.freshness import (
    FreshnessDiff,
    FreshnessFrontier,
    compute_changed_files_fingerprint,
    compute_freshness_diff,
)
from egtsr_runtime.services.repo_inspector import inspect_repo

if TYPE_CHECKING:
    from egtsr_runtime.db.uow import SqliteUnitOfWork


class FreshnessGateService:
    """Repo state freshness 추적 및 mismatch 차단."""

    def __init__(self, uow: SqliteUnitOfWork, cwd: str) -> None:
        self._uow = uow
        self._cwd = cwd

    def collect_frontier(
        self, session_id: str, source: str
    ) -> FreshnessFrontier:
        """현재 repo state를 수집하여 FreshnessFrontier 생성 및 저장."""
        now = datetime.now(timezone.utc).isoformat()
        repo_info = inspect_repo(self._cwd)

        # git status --porcelain으로 변경 파일 목록
        changed_files = self._get_changed_files()
        fingerprint = compute_changed_files_fingerprint(changed_files)

        # live tickets
        live_ticket_ids = self._get_live_ticket_ids(session_id)

        # open obligations
        open_obligation_ids = self._get_open_obligation_ids(session_id)

        # repo_hash: head + dirty + fingerprint의 결합 해시
        repo_hash = self._compute_repo_hash(
            head_hash=repo_info.head_hash or "",
            dirty=repo_info.dirty,
            fingerprint=fingerprint,
        )

        # last capsule
        last_capsule = self._uow.capsules.list_for_session(session_id)
        capsule_id = last_capsule[-1].id if last_capsule else ""

        frontier = FreshnessFrontier(
            session_id=session_id,
            repo_hash=repo_hash,
            branch=repo_info.branch or "",
            head_hash=repo_info.head_hash or "",
            dirty=repo_info.dirty,
            changed_files_fingerprint=fingerprint,
            live_ticket_ids=live_ticket_ids,
            open_obligation_ids=open_obligation_ids,
            capsule_id=capsule_id,
            source=source,
            created_at=now,
        )

        row_id = self._uow.freshness_repo.save(frontier)
        frontier.id = row_id
        return frontier

    def check_freshness(self, session_id: str) -> FreshnessDiff:
        """마지막 session_start frontier와 현재 state 비교."""
        expected = self._uow.freshness_repo.get_latest_by_source(
            session_id, "session_start"
        )
        if expected is None:
            # frontier 기록이 없으면 mismatch 없음으로 처리
            return FreshnessDiff()

        observed = self.collect_frontier(session_id, "user_prompt_submit")
        return compute_freshness_diff(expected, observed)

    def _get_changed_files(self) -> list[str]:
        """git status --porcelain에서 변경 파일 목록 추출."""
        import subprocess

        try:
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=self._cwd,
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                return []
            lines = result.stdout.strip().splitlines()
            # 각 줄: "XY filename" 또는 "XY old -> new"
            files = []
            for line in lines:
                if not line or len(line) < 4:
                    continue
                path = line[3:].strip()
                # rename의 경우 " -> " 뒤의 경로만
                if " -> " in path:
                    path = path.split(" -> ")[-1]
                files.append(path)
            return files
        except Exception:
            return []

    def _get_live_ticket_ids(self, session_id: str) -> list[str]:
        try:
            tickets = self._uow.invalidations.list_for_session(session_id)
            return [
                t.id
                for t in tickets
                if t.status == InvalidationStatus.LIVE
            ]
        except Exception:
            return []

    def _get_open_obligation_ids(self, session_id: str) -> list[str]:
        try:
            obligations = self._uow.obligations.list_open(session_id)
            return [o.id for o in obligations]
        except Exception:
            return []

    @staticmethod
    def _compute_repo_hash(
        head_hash: str, dirty: bool, fingerprint: str
    ) -> str:
        payload = json.dumps(
            {
                "head_hash": head_hash,
                "dirty": dirty,
                "fingerprint": fingerprint,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @staticmethod
    def describe_mismatch(diff: FreshnessDiff) -> str:
        """FreshnessDiff를 사람이 읽을 수 있는 문자열로 변환."""
        parts: list[str] = []
        if diff.head_changed:
            parts.append("head changed since session start")
        if diff.branch_changed:
            parts.append("branch changed")
        if diff.dirty_changed:
            parts.append("dirty state changed")
        if diff.files_changed:
            parts.append("changed files differ")
        if diff.new_tickets:
            parts.append(f"new invalidation tickets: {', '.join(diff.new_tickets)}")
        if diff.new_obligations:
            parts.append(f"new obligations: {', '.join(diff.new_obligations)}")
        return "; ".join(parts) if parts else "no mismatch"

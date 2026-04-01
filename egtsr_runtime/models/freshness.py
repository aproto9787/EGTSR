from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field


@dataclass(slots=True)
class FreshnessFrontier:
    """Repo state snapshot — freshness 판정의 기반."""

    session_id: str = ""
    repo_hash: str = ""
    branch: str = ""
    head_hash: str = ""
    dirty: bool = False
    changed_files_fingerprint: str = ""
    live_ticket_ids: list[str] = field(default_factory=list)
    open_obligation_ids: list[str] = field(default_factory=list)
    capsule_id: str = ""
    source: str = ""  # "session_start" | "user_prompt_submit"
    created_at: str = ""
    id: int | None = None


@dataclass(slots=True)
class FreshnessDiff:
    """두 frontier 간 차이."""

    head_changed: bool = False
    branch_changed: bool = False
    dirty_changed: bool = False
    files_changed: bool = False
    new_tickets: list[str] = field(default_factory=list)
    new_obligations: list[str] = field(default_factory=list)
    has_mismatch: bool = False


def compute_freshness_diff(
    expected: FreshnessFrontier, observed: FreshnessFrontier
) -> FreshnessDiff:
    """expected(마지막 기록) vs observed(현재 상태) 비교."""
    head_changed = expected.head_hash != observed.head_hash
    branch_changed = expected.branch != observed.branch
    dirty_changed = expected.dirty != observed.dirty
    files_changed = (
        expected.changed_files_fingerprint != observed.changed_files_fingerprint
    )
    new_tickets = [
        tid for tid in observed.live_ticket_ids if tid not in expected.live_ticket_ids
    ]
    new_obligations = [
        oid
        for oid in observed.open_obligation_ids
        if oid not in expected.open_obligation_ids
    ]

    has_mismatch = (
        head_changed
        or branch_changed
        or dirty_changed
        or files_changed
        or bool(new_tickets)
        or bool(new_obligations)
    )

    return FreshnessDiff(
        head_changed=head_changed,
        branch_changed=branch_changed,
        dirty_changed=dirty_changed,
        files_changed=files_changed,
        new_tickets=new_tickets,
        new_obligations=new_obligations,
        has_mismatch=has_mismatch,
    )


def compute_changed_files_fingerprint(files: list[str]) -> str:
    """변경 파일 목록의 결정론적 해시."""
    payload = json.dumps(sorted(files), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

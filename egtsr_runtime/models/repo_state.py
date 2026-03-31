from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class RepoState:
    session_id: str
    head_hash: str | None
    dirty: bool = False
    changed_files: list[str] = field(default_factory=list)
    last_scan_at: str = ""

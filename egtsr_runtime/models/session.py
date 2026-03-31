from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class Session:
    id: str
    repo_root: str
    branch: str | None
    head_hash: str | None
    status: str
    created_at: str
    updated_at: str

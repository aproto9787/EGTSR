from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Evidence:
    id: str
    session_id: str
    kind: str
    source_tool: str
    path: str | None = None
    scope_kind: str | None = None
    scope_ref: str | None = None
    file_hash: str | None = None
    polarity: str = "positive"
    excerpt: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class ChangedFilesDelta:
    files: list[str] = field(default_factory=list)
    symbols: list[str] | None = None

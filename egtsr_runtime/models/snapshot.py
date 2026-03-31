from __future__ import annotations

from dataclasses import dataclass, field

from egtsr_runtime.models.capsule import Capsule
from egtsr_runtime.models.event import Event
from egtsr_runtime.models.repo_state import RepoState
from egtsr_runtime.models.session import Session


@dataclass(slots=True)
class SessionSnapshot:
    session: Session
    repo_state: RepoState | None = None
    capsules: list[Capsule] = field(default_factory=list)
    events: list[Event] = field(default_factory=list)

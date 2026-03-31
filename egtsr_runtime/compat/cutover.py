"""Staged cutover and one-switch rollback (Step 09).

Implements the four-stage release cutover from document 11:

- Stage A: daemon on, projection off, compiler full
- Stage B: daemon on, projection shadow, compiler full
- Stage C: daemon on, projection on, compiler dual (shadow)
- Stage D: daemon on, projection on, compiler incremental (primary)

Rollback levels (from document 11 section 4):

- minimal:  compiler → full only
- medium:   compiler → full + projection → off
- full:     runtime_mode → legacy + compiler → full + projection → off
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

CutoverStage = Literal["baseline", "A", "B", "C", "D"]
RollbackLevel = Literal["minimal", "medium", "full"]

# Ordered stage sequence for advancement
_STAGE_ORDER: list[CutoverStage] = ["baseline", "A", "B", "C", "D"]

# Flag configurations for each stage
_STAGE_FLAGS: dict[CutoverStage, dict[str, object]] = {
    "baseline": {
        "runtime_mode": "legacy",
        "enable_daemon": False,
        "enable_incremental_compile": False,
        "enable_projection_tables": False,
        "enable_reverse_index": False,
    },
    "A": {
        "runtime_mode": "daemon",
        "enable_daemon": True,
        "enable_incremental_compile": False,
        "enable_projection_tables": False,
        "enable_reverse_index": True,
    },
    "B": {
        "runtime_mode": "daemon",
        "enable_daemon": True,
        "enable_incremental_compile": False,
        "enable_projection_tables": True,  # shadow projection
        "enable_reverse_index": True,
    },
    "C": {
        "runtime_mode": "shadow",
        "enable_daemon": True,
        "enable_incremental_compile": True,
        "enable_projection_tables": True,
        "enable_reverse_index": True,
    },
    "D": {
        "runtime_mode": "daemon",
        "enable_daemon": True,
        "enable_incremental_compile": True,
        "enable_projection_tables": True,
        "enable_reverse_index": True,
    },
}


@dataclass(slots=True)
class CutoverHistoryEntry:
    timestamp: str
    action: str  # "advance", "rollback", "set"
    from_stage: CutoverStage
    to_stage: CutoverStage
    detail: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class CutoverState:
    current_stage: CutoverStage = "baseline"
    history: list[CutoverHistoryEntry] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "current_stage": self.current_stage,
            "history": [h.to_dict() for h in self.history],
        }


class CutoverManager:
    """Manage staged cutover and rollback via runtime_flags.json."""

    def __init__(self, egtsr_dir: str) -> None:
        self._egtsr_dir = egtsr_dir
        self._flags_path = Path(egtsr_dir) / "runtime_flags.json"
        self._state_path = Path(egtsr_dir) / "cutover_state.json"

    def status(self) -> CutoverState:
        """Read current cutover state."""
        return self._load_state()

    def current_stage(self) -> CutoverStage:
        """Determine current stage from runtime flags."""
        state = self._load_state()
        return state.current_stage

    def stage_flags(self, stage: CutoverStage) -> dict[str, object]:
        """Return the flag configuration for a given stage."""
        return dict(_STAGE_FLAGS[stage])

    def advance(self) -> CutoverState:
        """Advance to the next stage. Raises ValueError if already at D."""
        state = self._load_state()
        idx = _STAGE_ORDER.index(state.current_stage)
        if idx >= len(_STAGE_ORDER) - 1:
            raise ValueError(
                f"Already at final stage '{state.current_stage}', cannot advance"
            )
        next_stage = _STAGE_ORDER[idx + 1]
        return self._transition(state, next_stage, action="advance")

    def set_stage(self, stage: CutoverStage) -> CutoverState:
        """Set a specific stage (any direction)."""
        if stage not in _STAGE_ORDER:
            raise ValueError(f"Invalid stage: {stage}")
        state = self._load_state()
        if state.current_stage == stage:
            return state
        return self._transition(state, stage, action="set")

    def rollback(self, level: RollbackLevel = "full") -> CutoverState:
        """Execute rollback to legacy mode.

        Rollback is atomic: flags are written in a single file update.
        The cutover state is reset to baseline regardless of level,
        because any rollback means the cutover sequence must restart.
        """
        state = self._load_state()
        prev_stage = state.current_stage

        flags = self._load_flags()

        if level == "minimal":
            # Only compiler reset
            flags["enable_incremental_compile"] = False
            detail = "compiler → full"
        elif level == "medium":
            # Compiler + projection reset
            flags["enable_incremental_compile"] = False
            flags["enable_projection_tables"] = False
            detail = "compiler → full, projection → off"
        else:
            # Full rollback — everything to legacy
            flags["runtime_mode"] = "legacy"
            flags["enable_daemon"] = False
            flags["enable_incremental_compile"] = False
            flags["enable_projection_tables"] = False
            flags["enable_reverse_index"] = False
            detail = "full rollback → legacy mode"

        self._write_flags(flags)

        target_stage: CutoverStage = "baseline"
        entry = CutoverHistoryEntry(
            timestamp=_now_iso(),
            action="rollback",
            from_stage=prev_stage,
            to_stage=target_stage,
            detail=f"level={level}: {detail}",
        )
        state.current_stage = target_stage
        state.history.append(entry)
        self._save_state(state)
        return state

    def _transition(
        self,
        state: CutoverState,
        target: CutoverStage,
        action: str,
    ) -> CutoverState:
        """Apply flag transition and record history."""
        prev = state.current_stage
        flags = _STAGE_FLAGS[target]
        self._write_flags(dict(flags))

        entry = CutoverHistoryEntry(
            timestamp=_now_iso(),
            action=action,
            from_stage=prev,
            to_stage=target,
        )
        state.current_stage = target
        state.history.append(entry)
        self._save_state(state)
        return state

    def _load_flags(self) -> dict:
        if self._flags_path.is_file():
            try:
                return json.loads(self._flags_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return {}

    def _write_flags(self, flags: dict) -> None:
        self._flags_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._flags_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(flags, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(self._flags_path)

    def _load_state(self) -> CutoverState:
        if not self._state_path.is_file():
            return CutoverState()
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
            history = [
                CutoverHistoryEntry(**h)
                for h in data.get("history", [])
            ]
            stage = data.get("current_stage", "baseline")
            if stage not in _STAGE_ORDER:
                stage = "baseline"
            return CutoverState(current_stage=stage, history=history)
        except (json.JSONDecodeError, OSError, TypeError):
            return CutoverState()

    def _save_state(self, state: CutoverState) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._state_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps(state.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(self._state_path)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()

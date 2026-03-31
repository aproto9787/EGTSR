from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from egtsr_runtime.services.resume_gate import ResumeGateState


class SnapshotWriter:
    def __init__(self, paths):
        self._paths = paths

    def write_last_good_capsule(self, capsule_data: dict) -> None:
        """Write last_good_decision_capsule.json to .egtsr/."""

        self._write_json(self._paths.last_good_capsule_path, capsule_data)

    def write_resume_gate(self, gate: ResumeGateState) -> None:
        """Write resume_gate.json to .egtsr/."""

        self._write_json(self._paths.resume_gate_path, asdict(gate))

    def read_resume_gate(self) -> ResumeGateState | None:
        """Read resume_gate.json if present and valid."""

        path = Path(self._paths.resume_gate_path)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return None
        if not isinstance(data, dict):
            return None

        required_rechecks = data.get("required_rechecks", [])
        if not isinstance(required_rechecks, list):
            required_rechecks = []

        reason = data.get("reason")
        if reason is not None and not isinstance(reason, str):
            reason = None

        return ResumeGateState(
            session_id=str(data.get("session_id") or ""),
            edit_blocked=bool(data.get("edit_blocked", False)),
            reason=reason,
            required_rechecks=[str(item) for item in required_rechecks],
            updated_at=str(data.get("updated_at") or ""),
        )

    @staticmethod
    def _write_json(path_str: str, payload: dict) -> None:
        path = Path(path_str)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

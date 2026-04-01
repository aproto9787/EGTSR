from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from egtsr_runtime.services.resume_gate import ResumeGateState


class SnapshotWriter:
    def __init__(self, paths):
        self._paths = paths

    def write_last_good_capsule(self, capsule_data: dict) -> None:
        """Write last_good_decision_capsule.json — export/debug only, not authoritative.

        The DB (capsules table) is the single source of truth for capsule data.
        This JSON file exists for external inspection and debugging.
        """
        self._write_json(self._paths.last_good_capsule_path, capsule_data)

    def write_resume_gate(self, gate: ResumeGateState) -> None:
        """Write resume_gate.json — export/debug only, not authoritative.

        The DB (resume_gate_state table) is the single source of truth for gate
        decisions.  This JSON file exists for external inspection and debugging.
        """
        self._write_json(self._paths.resume_gate_path, asdict(gate))

    @staticmethod
    def _write_json(path_str: str, payload: dict) -> None:
        path = Path(path_str)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

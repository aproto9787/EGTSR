from __future__ import annotations

import sqlite3

from egtsr_runtime.repositories._base import dump_json, load_list
from egtsr_runtime.services.resume_gate import ResumeGateState


class SqliteResumeGateRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, session_id: str) -> ResumeGateState | None:
        row = self.conn.execute(
            "SELECT * FROM resume_gate_state WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return ResumeGateState(
            session_id=row["session_id"],
            edit_blocked=bool(row["edit_blocked"]),
            reason=row["reason"],
            required_rechecks=load_list(row["required_rechecks_json"]),
            updated_at=row["updated_at"],
        )

    def upsert(self, gate: ResumeGateState) -> None:
        self.conn.execute(
            """
            INSERT INTO resume_gate_state
                (session_id, edit_blocked, reason, required_rechecks_json, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                edit_blocked = excluded.edit_blocked,
                reason = excluded.reason,
                required_rechecks_json = excluded.required_rechecks_json,
                updated_at = excluded.updated_at
            """,
            (
                gate.session_id,
                int(gate.edit_blocked),
                gate.reason,
                dump_json(gate.required_rechecks),
                gate.updated_at,
            ),
        )

"""SessionFrontierRepository — session meta fast lookup."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(slots=True)
class SessionFrontierRow:
    session_id: str
    frontier_version: int
    dirty_obligation_count: int
    last_compiled_capsule_id: str | None
    last_frontier_hash: str | None
    last_compiled_at: str | None
    updated_at: str


class SqliteSessionFrontierRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, session_id: str) -> SessionFrontierRow | None:
        row = self.conn.execute(
            "SELECT * FROM session_frontier WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return self._from_row(row) if row is not None else None

    def get_frontier_version(self, session_id: str) -> int | None:
        row = self.conn.execute(
            "SELECT frontier_version FROM session_frontier WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return row["frontier_version"] if row is not None else None

    def update_last_compiled(
        self,
        session_id: str,
        capsule_id: str,
        frontier_hash: str,
        compiled_at: str,
    ) -> None:
        self.conn.execute(
            """UPDATE session_frontier SET
               last_compiled_capsule_id = ?,
               last_frontier_hash = ?,
               last_compiled_at = ?,
               updated_at = ?
               WHERE session_id = ?""",
            (capsule_id, frontier_hash, compiled_at, compiled_at, session_id),
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> SessionFrontierRow:
        return SessionFrontierRow(
            session_id=row["session_id"],
            frontier_version=row["frontier_version"],
            dirty_obligation_count=row["dirty_obligation_count"],
            last_compiled_capsule_id=row["last_compiled_capsule_id"],
            last_frontier_hash=row["last_frontier_hash"],
            last_compiled_at=row["last_compiled_at"],
            updated_at=row["updated_at"],
        )

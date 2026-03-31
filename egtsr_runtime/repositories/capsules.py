from __future__ import annotations

import sqlite3

from egtsr_runtime.enums import VerifyPhase
from egtsr_runtime.models import Capsule
from egtsr_runtime.repositories._base import dump_json, load_dict


class SqliteCapsuleRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create(self, capsule: Capsule) -> None:
        self.conn.execute(
            """
            INSERT INTO capsules (
                id, session_id, phase, frontier_hash, content, token_count,
                audit_pass, audit_report_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                capsule.id,
                capsule.session_id,
                capsule.phase.value,
                capsule.frontier_hash,
                capsule.content,
                capsule.token_count,
                int(capsule.audit_pass),
                dump_json(capsule.audit_report),
                capsule.created_at,
            ),
        )

    def get(self, capsule_id: str) -> Capsule | None:
        row = self.conn.execute(
            "SELECT * FROM capsules WHERE id = ?",
            (capsule_id,),
        ).fetchone()
        return self._from_row(row) if row is not None else None

    def list_for_session(self, session_id: str) -> list[Capsule]:
        rows = self.conn.execute(
            "SELECT * FROM capsules WHERE session_id = ? ORDER BY created_at, id",
            (session_id,),
        ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Capsule:
        return Capsule(
            id=row["id"],
            session_id=row["session_id"],
            phase=VerifyPhase(row["phase"]),
            frontier_hash=row["frontier_hash"],
            content=row["content"],
            token_count=row["token_count"],
            audit_pass=bool(row["audit_pass"]),
            audit_report=load_dict(row["audit_report_json"]),
            created_at=row["created_at"],
        )

from __future__ import annotations

import sqlite3

from egtsr_runtime.enums import ObligationStatus
from egtsr_runtime.models import Obligation
from egtsr_runtime.repositories._base import dump_json, load_dict


class SqliteObligationRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, obligation_id: str) -> Obligation | None:
        row = self.conn.execute(
            "SELECT * FROM obligations WHERE id = ?",
            (obligation_id,),
        ).fetchone()
        return self._from_row(row) if row is not None else None

    def list_for_session(self, session_id: str) -> list[Obligation]:
        rows = self.conn.execute(
            "SELECT * FROM obligations WHERE session_id = ? ORDER BY created_at, id",
            (session_id,),
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def list_open(self, session_id: str) -> list[Obligation]:
        rows = self.conn.execute(
            """
            SELECT * FROM obligations
            WHERE session_id = ? AND status != ?
            ORDER BY created_at, id
            """,
            (session_id, ObligationStatus.VERIFIED.value),
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def upsert(self, obligation: Obligation) -> None:
        self.conn.execute(
            """
            INSERT INTO obligations (
                id, session_id, source, statement, priority, status,
                acceptance_check, metadata_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                session_id = excluded.session_id,
                source = excluded.source,
                statement = excluded.statement,
                priority = excluded.priority,
                status = excluded.status,
                acceptance_check = excluded.acceptance_check,
                metadata_json = excluded.metadata_json,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            (
                obligation.id,
                obligation.session_id,
                obligation.source,
                obligation.statement,
                obligation.priority,
                obligation.status.value,
                obligation.acceptance_check,
                dump_json(obligation.metadata),
                obligation.created_at,
                obligation.updated_at,
            ),
        )

    def mark_status(self, obligation_id: str, status: str) -> None:
        self.conn.execute(
            "UPDATE obligations SET status = ? WHERE id = ?",
            (status, obligation_id),
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Obligation:
        return Obligation(
            id=row["id"],
            session_id=row["session_id"],
            source=row["source"],
            statement=row["statement"],
            priority=row["priority"],
            status=ObligationStatus(row["status"]),
            acceptance_check=row["acceptance_check"],
            metadata=load_dict(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

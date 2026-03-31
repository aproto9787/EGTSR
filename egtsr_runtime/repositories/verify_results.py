from __future__ import annotations

import sqlite3

from egtsr_runtime.enums import VerifyPhase
from egtsr_runtime.models import VerifyResult
from egtsr_runtime.repositories._base import dump_json, load_dict, load_list


class SqliteVerifyRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create(self, result: VerifyResult) -> None:
        self.conn.execute(
            """
            INSERT INTO verify_results (
                id, session_id, phase, outcome, affected_obligation_ids_json,
                excerpt, metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.id,
                result.session_id,
                result.phase.value,
                result.outcome,
                dump_json(result.affected_obligation_ids),
                result.excerpt,
                dump_json(result.metadata),
                result.created_at,
            ),
        )

    def get(self, result_id: str) -> VerifyResult | None:
        row = self.conn.execute(
            "SELECT * FROM verify_results WHERE id = ?",
            (result_id,),
        ).fetchone()
        return self._from_row(row) if row is not None else None

    def list_for_session(self, session_id: str) -> list[VerifyResult]:
        rows = self.conn.execute(
            "SELECT * FROM verify_results WHERE session_id = ? ORDER BY created_at, id",
            (session_id,),
        ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: sqlite3.Row) -> VerifyResult:
        return VerifyResult(
            id=row["id"],
            session_id=row["session_id"],
            phase=VerifyPhase(row["phase"]),
            outcome=row["outcome"],
            affected_obligation_ids=load_list(row["affected_obligation_ids_json"]),
            excerpt=row["excerpt"],
            metadata=load_dict(row["metadata_json"]),
            created_at=row["created_at"],
        )

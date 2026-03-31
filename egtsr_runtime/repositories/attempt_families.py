from __future__ import annotations

import sqlite3

from egtsr_runtime.models import AttemptFamily
from egtsr_runtime.repositories._base import dump_json, load_dict, load_list


class SqliteAttemptFamilyRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, family_id: str) -> AttemptFamily | None:
        row = self.conn.execute(
            "SELECT * FROM attempt_families WHERE id = ?",
            (family_id,),
        ).fetchone()
        return self._from_row(row) if row is not None else None

    def list_for_session(self, session_id: str) -> list[AttemptFamily]:
        rows = self.conn.execute(
            "SELECT * FROM attempt_families WHERE session_id = ? ORDER BY created_at, id",
            (session_id,),
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def get_by_signature(self, session_id: str, signature: str) -> AttemptFamily | None:
        row = self.conn.execute(
            "SELECT * FROM attempt_families WHERE session_id = ? AND signature = ?",
            (session_id, signature),
        ).fetchone()
        return self._from_row(row) if row is not None else None

    def list_recent_failures_by_obligation_ids(
        self, obligation_ids: list[str], limit_per_obligation: int = 5
    ) -> list[AttemptFamily]:
        if not obligation_ids:
            return []
        placeholders = ",".join("?" for _ in obligation_ids)
        rows = self.conn.execute(
            f"""SELECT * FROM (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY obligation_id ORDER BY updated_at DESC
                    ) AS rn
                    FROM attempt_families
                    WHERE obligation_id IN ({placeholders}) AND last_outcome = 'fail'
                ) WHERE rn <= ?
                ORDER BY obligation_id, updated_at DESC""",  # noqa: S608
            (*obligation_ids, limit_per_obligation),
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def upsert(self, family: AttemptFamily) -> None:
        self.conn.execute(
            """
            INSERT INTO attempt_families (
                id, session_id, obligation_id, signature, touched_scope_json,
                fail_count, last_outcome, summary, metadata_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                session_id = excluded.session_id,
                obligation_id = excluded.obligation_id,
                signature = excluded.signature,
                touched_scope_json = excluded.touched_scope_json,
                fail_count = excluded.fail_count,
                last_outcome = excluded.last_outcome,
                summary = excluded.summary,
                metadata_json = excluded.metadata_json,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            (
                family.id,
                family.session_id,
                family.obligation_id,
                family.signature,
                dump_json(family.touched_scope),
                family.fail_count,
                family.last_outcome,
                family.summary,
                dump_json(family.metadata),
                family.created_at,
                family.updated_at,
            ),
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> AttemptFamily:
        return AttemptFamily(
            id=row["id"],
            session_id=row["session_id"],
            obligation_id=row["obligation_id"],
            signature=row["signature"],
            touched_scope=load_list(row["touched_scope_json"]),
            fail_count=row["fail_count"],
            last_outcome=row["last_outcome"],
            summary=row["summary"],
            metadata=load_dict(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

from __future__ import annotations

import sqlite3

from egtsr_runtime.enums import AssertionStatus
from egtsr_runtime.models import Assertion
from egtsr_runtime.repositories._base import dump_json, load_dict, load_list


class SqliteAssertionRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, assertion_id: str) -> Assertion | None:
        row = self.conn.execute(
            "SELECT * FROM assertions WHERE id = ?",
            (assertion_id,),
        ).fetchone()
        return self._from_row(row) if row is not None else None

    def list_for_session(self, session_id: str) -> list[Assertion]:
        rows = self.conn.execute(
            "SELECT * FROM assertions WHERE session_id = ? ORDER BY created_at, id",
            (session_id,),
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def list_by_ids(self, assertion_ids: list[str]) -> list[Assertion]:
        if not assertion_ids:
            return []
        placeholders = ",".join("?" for _ in assertion_ids)
        rows = self.conn.execute(
            f"SELECT * FROM assertions WHERE id IN ({placeholders}) ORDER BY created_at, id",  # noqa: S608
            assertion_ids,
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def list_active_by_obligation_ids(self, obligation_ids: list[str]) -> list[Assertion]:
        if not obligation_ids:
            return []
        placeholders = ",".join("?" for _ in obligation_ids)
        rows = self.conn.execute(
            f"""SELECT * FROM assertions
                WHERE obligation_id IN ({placeholders}) AND status != ?
                ORDER BY obligation_id, created_at, id""",  # noqa: S608
            (*obligation_ids, AssertionStatus.STALE.value),
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def bulk_upsert(self, assertions: list[Assertion]) -> None:
        if not assertions:
            return
        for assertion in assertions:
            self.upsert(assertion)

    def bulk_mark_stale(self, assertion_ids: list[str], updated_at: str) -> None:
        if not assertion_ids:
            return
        placeholders = ",".join("?" for _ in assertion_ids)
        self.conn.execute(
            f"UPDATE assertions SET status = ?, updated_at = ? WHERE id IN ({placeholders})",  # noqa: S608
            (AssertionStatus.STALE.value, updated_at, *assertion_ids),
        )

    def list_obligation_ids_for_assertions(self, assertion_ids: list[str]) -> list[str]:
        if not assertion_ids:
            return []
        placeholders = ",".join("?" for _ in assertion_ids)
        rows = self.conn.execute(
            f"""SELECT DISTINCT obligation_id FROM assertions
                WHERE id IN ({placeholders}) AND obligation_id IS NOT NULL""",  # noqa: S608
            assertion_ids,
        ).fetchall()
        return [row["obligation_id"] for row in rows]

    def upsert(self, assertion: Assertion) -> None:
        self.conn.execute(
            """
            INSERT INTO assertions (
                id, session_id, obligation_id, statement, scope_kind, scope_ref,
                status, confidence, evidence_ids_json, metadata_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                session_id = excluded.session_id,
                obligation_id = excluded.obligation_id,
                statement = excluded.statement,
                scope_kind = excluded.scope_kind,
                scope_ref = excluded.scope_ref,
                status = excluded.status,
                confidence = excluded.confidence,
                evidence_ids_json = excluded.evidence_ids_json,
                metadata_json = excluded.metadata_json,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            (
                assertion.id,
                assertion.session_id,
                assertion.obligation_id,
                assertion.statement,
                assertion.scope_kind,
                assertion.scope_ref,
                assertion.status.value,
                assertion.confidence,
                dump_json(assertion.evidence_ids),
                dump_json(assertion.metadata),
                assertion.created_at,
                assertion.updated_at,
            ),
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Assertion:
        return Assertion(
            id=row["id"],
            session_id=row["session_id"],
            obligation_id=row["obligation_id"],
            statement=row["statement"],
            scope_kind=row["scope_kind"],
            scope_ref=row["scope_ref"],
            status=AssertionStatus(row["status"]),
            confidence=row["confidence"],
            evidence_ids=load_list(row["evidence_ids_json"]),
            metadata=load_dict(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

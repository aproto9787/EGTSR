"""AssertionEvidenceLinkRepository — assertion <-> evidence link lookup."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AssertionEvidenceLinkRow:
    session_id: str
    assertion_id: str
    evidence_id: str
    created_at: str


class SqliteAssertionEvidenceLinkRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def list_evidence_ids_for_assertion(self, assertion_id: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT evidence_id FROM assertion_evidence_links WHERE assertion_id = ? ORDER BY created_at",
            (assertion_id,),
        ).fetchall()
        return [row["evidence_id"] for row in rows]

    def list_assertion_ids_for_evidence(self, evidence_id: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT assertion_id FROM assertion_evidence_links WHERE evidence_id = ? ORDER BY created_at",
            (evidence_id,),
        ).fetchall()
        return [row["assertion_id"] for row in rows]

    def list_evidence_ids_for_assertions(self, assertion_ids: list[str]) -> dict[str, list[str]]:
        if not assertion_ids:
            return {}
        placeholders = ",".join("?" for _ in assertion_ids)
        rows = self.conn.execute(
            f"""SELECT assertion_id, evidence_id FROM assertion_evidence_links
                WHERE assertion_id IN ({placeholders})
                ORDER BY assertion_id, created_at""",  # noqa: S608
            assertion_ids,
        ).fetchall()
        result: dict[str, list[str]] = {}
        for row in rows:
            result.setdefault(row["assertion_id"], []).append(row["evidence_id"])
        return result

    def list_assertion_ids_for_evidences(self, evidence_ids: list[str]) -> list[str]:
        if not evidence_ids:
            return []
        placeholders = ",".join("?" for _ in evidence_ids)
        rows = self.conn.execute(
            f"""SELECT DISTINCT assertion_id FROM assertion_evidence_links
                WHERE evidence_id IN ({placeholders})""",  # noqa: S608
            evidence_ids,
        ).fetchall()
        return [row["assertion_id"] for row in rows]

    def list_links_for_session(self, session_id: str) -> list[AssertionEvidenceLinkRow]:
        rows = self.conn.execute(
            "SELECT * FROM assertion_evidence_links WHERE session_id = ? ORDER BY created_at",
            (session_id,),
        ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: sqlite3.Row) -> AssertionEvidenceLinkRow:
        return AssertionEvidenceLinkRow(
            session_id=row["session_id"],
            assertion_id=row["assertion_id"],
            evidence_id=row["evidence_id"],
            created_at=row["created_at"],
        )

from __future__ import annotations

import sqlite3

from egtsr_runtime.models import Evidence
from egtsr_runtime.repositories._base import dump_json, load_dict


class SqliteEvidenceRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create(self, evidence: Evidence) -> None:
        self.conn.execute(
            """
            INSERT INTO evidence (
                id, session_id, kind, source_tool, path, scope_kind, scope_ref,
                file_hash, polarity, excerpt, metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                evidence.id,
                evidence.session_id,
                evidence.kind,
                evidence.source_tool,
                evidence.path,
                evidence.scope_kind,
                evidence.scope_ref,
                evidence.file_hash,
                evidence.polarity,
                evidence.excerpt,
                dump_json(evidence.metadata),
                evidence.created_at,
            ),
        )

    def get(self, evidence_id: str) -> Evidence | None:
        row = self.conn.execute(
            "SELECT * FROM evidence WHERE id = ?",
            (evidence_id,),
        ).fetchone()
        return self._from_row(row) if row is not None else None

    def list_for_session(self, session_id: str) -> list[Evidence]:
        rows = self.conn.execute(
            "SELECT * FROM evidence WHERE session_id = ? ORDER BY created_at, id",
            (session_id,),
        ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Evidence:
        return Evidence(
            id=row["id"],
            session_id=row["session_id"],
            kind=row["kind"],
            source_tool=row["source_tool"],
            path=row["path"],
            scope_kind=row["scope_kind"],
            scope_ref=row["scope_ref"],
            file_hash=row["file_hash"],
            polarity=row["polarity"],
            excerpt=row["excerpt"],
            metadata=load_dict(row["metadata_json"]),
            created_at=row["created_at"],
        )

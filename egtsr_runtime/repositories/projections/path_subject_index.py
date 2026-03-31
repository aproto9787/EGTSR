"""PathSubjectIndexRepository — path -> subject reverse-index lookup."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PathSubjectRow:
    session_id: str
    normalized_path: str
    subject_type: str
    subject_id: str
    role: str
    updated_at: str


class SqlitePathSubjectIndexRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def list_subjects_for_paths(
        self, session_id: str, paths: list[str], subject_type: str | None = None
    ) -> list[PathSubjectRow]:
        if not paths:
            return []
        placeholders = ",".join("?" for _ in paths)
        if subject_type is not None:
            rows = self.conn.execute(
                f"""SELECT * FROM path_subject_index
                    WHERE session_id = ? AND normalized_path IN ({placeholders})
                    AND subject_type = ?
                    ORDER BY normalized_path, subject_type, subject_id""",  # noqa: S608
                (session_id, *paths, subject_type),
            ).fetchall()
        else:
            rows = self.conn.execute(
                f"""SELECT * FROM path_subject_index
                    WHERE session_id = ? AND normalized_path IN ({placeholders})
                    ORDER BY normalized_path, subject_type, subject_id""",  # noqa: S608
                (session_id, *paths),
            ).fetchall()
        return [self._from_row(row) for row in rows]

    def list_subject_ids_for_paths(
        self, session_id: str, paths: list[str], subject_type: str
    ) -> list[str]:
        if not paths:
            return []
        placeholders = ",".join("?" for _ in paths)
        rows = self.conn.execute(
            f"""SELECT DISTINCT subject_id FROM path_subject_index
                WHERE session_id = ? AND normalized_path IN ({placeholders})
                AND subject_type = ?""",  # noqa: S608
            (session_id, *paths, subject_type),
        ).fetchall()
        return [row["subject_id"] for row in rows]

    def list_paths_for_subject(
        self, session_id: str, subject_type: str, subject_id: str
    ) -> list[str]:
        rows = self.conn.execute(
            """SELECT DISTINCT normalized_path FROM path_subject_index
               WHERE session_id = ? AND subject_type = ? AND subject_id = ?""",
            (session_id, subject_type, subject_id),
        ).fetchall()
        return [row["normalized_path"] for row in rows]

    def delete_for_subject(self, subject_type: str, subject_id: str) -> None:
        self.conn.execute(
            "DELETE FROM path_subject_index WHERE subject_type = ? AND subject_id = ?",
            (subject_type, subject_id),
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> PathSubjectRow:
        return PathSubjectRow(
            session_id=row["session_id"],
            normalized_path=row["normalized_path"],
            subject_type=row["subject_type"],
            subject_id=row["subject_id"],
            role=row["role"],
            updated_at=row["updated_at"],
        )

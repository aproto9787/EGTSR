from __future__ import annotations

import sqlite3

from egtsr_runtime.models import Session


class SqliteSessionRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create(self, session: Session) -> None:
        self.conn.execute(
            """
            INSERT INTO sessions (id, repo_root, branch, head_hash, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.id,
                session.repo_root,
                session.branch,
                session.head_hash,
                session.status,
                session.created_at,
                session.updated_at,
            ),
        )

    def get(self, session_id: str) -> Session | None:
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return Session(
            id=row["id"],
            repo_root=row["repo_root"],
            branch=row["branch"],
            head_hash=row["head_hash"],
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def update(self, session: Session) -> None:
        self.conn.execute(
            """
            UPDATE sessions
            SET repo_root = ?, branch = ?, head_hash = ?, status = ?, created_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                session.repo_root,
                session.branch,
                session.head_hash,
                session.status,
                session.created_at,
                session.updated_at,
                session.id,
            ),
        )

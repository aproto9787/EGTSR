from __future__ import annotations

import sqlite3

from egtsr_runtime.models import RepoState
from egtsr_runtime.repositories._base import dump_json, load_list


class SqliteRepoStateRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, session_id: str) -> RepoState | None:
        row = self.conn.execute(
            "SELECT * FROM repo_state WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if row is None:
            return None
        return RepoState(
            session_id=row["session_id"],
            head_hash=row["head_hash"],
            dirty=bool(row["dirty"]),
            changed_files=load_list(row["changed_files_json"]),
            last_scan_at=row["last_scan_at"],
        )

    def upsert(self, repo_state: RepoState) -> None:
        self.conn.execute(
            """
            INSERT INTO repo_state (session_id, head_hash, dirty, changed_files_json, last_scan_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                head_hash = excluded.head_hash,
                dirty = excluded.dirty,
                changed_files_json = excluded.changed_files_json,
                last_scan_at = excluded.last_scan_at
            """,
            (
                repo_state.session_id,
                repo_state.head_hash,
                int(repo_state.dirty),
                dump_json(repo_state.changed_files),
                repo_state.last_scan_at,
            ),
        )

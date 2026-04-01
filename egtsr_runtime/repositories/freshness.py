from __future__ import annotations

import sqlite3

from egtsr_runtime.models.freshness import FreshnessFrontier
from egtsr_runtime.repositories._base import dump_json, load_list


class SqliteFreshnessRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def save(self, frontier: FreshnessFrontier) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO freshness_frontiers
                (session_id, repo_hash, branch, head_hash, dirty,
                 changed_files_fingerprint, live_ticket_ids_json,
                 open_obligation_ids_json, capsule_id, source, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                frontier.session_id,
                frontier.repo_hash,
                frontier.branch,
                frontier.head_hash,
                int(frontier.dirty),
                frontier.changed_files_fingerprint,
                dump_json(frontier.live_ticket_ids),
                dump_json(frontier.open_obligation_ids),
                frontier.capsule_id,
                frontier.source,
                frontier.created_at,
            ),
        )
        return cursor.lastrowid  # type: ignore[return-value]

    def get_latest(self, session_id: str) -> FreshnessFrontier | None:
        row = self.conn.execute(
            """
            SELECT * FROM freshness_frontiers
            WHERE session_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
        return self._row_to_model(row) if row else None

    def get_latest_by_source(
        self, session_id: str, source: str
    ) -> FreshnessFrontier | None:
        row = self.conn.execute(
            """
            SELECT * FROM freshness_frontiers
            WHERE session_id = ? AND source = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (session_id, source),
        ).fetchone()
        return self._row_to_model(row) if row else None

    @staticmethod
    def _row_to_model(row: sqlite3.Row) -> FreshnessFrontier:
        return FreshnessFrontier(
            id=row["id"],
            session_id=row["session_id"],
            repo_hash=row["repo_hash"],
            branch=row["branch"] or "",
            head_hash=row["head_hash"] or "",
            dirty=bool(row["dirty"]),
            changed_files_fingerprint=row["changed_files_fingerprint"] or "",
            live_ticket_ids=load_list(row["live_ticket_ids_json"]),
            open_obligation_ids=load_list(row["open_obligation_ids_json"]),
            capsule_id=row["capsule_id"] or "",
            source=row["source"],
            created_at=row["created_at"],
        )

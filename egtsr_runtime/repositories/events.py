from __future__ import annotations

import sqlite3

from egtsr_runtime.models import Event
from egtsr_runtime.repositories._base import dump_json, load_dict


class SqliteEventRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def create(self, event: Event) -> None:
        self.conn.execute(
            "INSERT INTO events (id, session_id, event_type, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                event.id,
                event.session_id,
                event.event_type,
                dump_json(event.payload),
                event.created_at,
            ),
        )

    def get(self, event_id: str) -> Event | None:
        row = self.conn.execute(
            "SELECT * FROM events WHERE id = ?",
            (event_id,),
        ).fetchone()
        return self._from_row(row) if row is not None else None

    def list_for_session(self, session_id: str) -> list[Event]:
        rows = self.conn.execute(
            "SELECT * FROM events WHERE session_id = ? ORDER BY created_at, id",
            (session_id,),
        ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: sqlite3.Row) -> Event:
        return Event(
            id=row["id"],
            session_id=row["session_id"],
            event_type=row["event_type"],
            payload=load_dict(row["payload_json"]),
            created_at=row["created_at"],
        )

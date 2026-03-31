"""ObligationFrontierRepository — open/dirty obligation fast lookup."""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field


@dataclass(slots=True)
class ObligationFrontierRow:
    session_id: str
    obligation_id: str
    priority: int
    obligation_status: str
    dirty: bool
    dirty_reasons: list[str]
    supported_assertion_count: int = 0
    confirmed_assertion_count: int = 0
    speculative_assertion_count: int = 0
    refuted_assertion_count: int = 0
    live_stale_ticket_count: int = 0
    recent_failed_family_count: int = 0
    rendered_positive_json: str = "[]"
    rendered_negative_json: str = "[]"
    rendered_uncertainty_json: str = "[]"
    suggested_next_check: str | None = None
    render_hash: str | None = None
    render_version: int = 0
    token_estimate: int = 0
    last_rebuilt_at: str | None = None
    updated_at: str = ""


class SqliteObligationFrontierRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, obligation_id: str) -> ObligationFrontierRow | None:
        row = self.conn.execute(
            "SELECT * FROM obligation_frontier WHERE obligation_id = ?",
            (obligation_id,),
        ).fetchone()
        return self._from_row(row) if row is not None else None

    def list_dirty(self, session_id: str) -> list[ObligationFrontierRow]:
        rows = self.conn.execute(
            """SELECT * FROM obligation_frontier
               WHERE session_id = ? AND dirty = 1
               ORDER BY priority, obligation_status, obligation_id""",
            (session_id,),
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def list_dirty_ids(self, session_id: str) -> list[str]:
        rows = self.conn.execute(
            "SELECT obligation_id FROM obligation_frontier WHERE session_id = ? AND dirty = 1",
            (session_id,),
        ).fetchall()
        return [row["obligation_id"] for row in rows]

    def list_open(self, session_id: str) -> list[ObligationFrontierRow]:
        rows = self.conn.execute(
            """SELECT * FROM obligation_frontier
               WHERE session_id = ? AND obligation_status != 'verified'
               ORDER BY priority, obligation_id""",
            (session_id,),
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def list_open_ids(self, session_id: str) -> list[str]:
        rows = self.conn.execute(
            """SELECT obligation_id FROM obligation_frontier
               WHERE session_id = ? AND obligation_status != 'verified'""",
            (session_id,),
        ).fetchall()
        return [row["obligation_id"] for row in rows]

    def mark_clean(self, obligation_id: str, updated_at: str) -> None:
        self.conn.execute(
            "UPDATE obligation_frontier SET dirty = 0, dirty_reasons_json = '[]', updated_at = ? WHERE obligation_id = ?",
            (updated_at, obligation_id),
        )

    def bulk_mark_clean(self, obligation_ids: list[str], updated_at: str) -> None:
        if not obligation_ids:
            return
        placeholders = ",".join("?" for _ in obligation_ids)
        self.conn.execute(
            f"UPDATE obligation_frontier SET dirty = 0, dirty_reasons_json = '[]', updated_at = ? WHERE obligation_id IN ({placeholders})",  # noqa: S608
            (updated_at, *obligation_ids),
        )

    def update_render_cache(
        self,
        obligation_id: str,
        rendered_positive_json: str,
        rendered_negative_json: str,
        rendered_uncertainty_json: str,
        suggested_next_check: str,
        render_hash: str,
        token_estimate: int,
        updated_at: str,
    ) -> None:
        self.conn.execute(
            """UPDATE obligation_frontier SET
               rendered_positive_json = ?,
               rendered_negative_json = ?,
               rendered_uncertainty_json = ?,
               suggested_next_check = ?,
               render_hash = ?,
               render_version = render_version + 1,
               token_estimate = ?,
               last_rebuilt_at = ?,
               updated_at = ?
               WHERE obligation_id = ?""",
            (
                rendered_positive_json,
                rendered_negative_json,
                rendered_uncertainty_json,
                suggested_next_check,
                render_hash,
                token_estimate,
                updated_at,
                updated_at,
                obligation_id,
            ),
        )

    def list_for_session(self, session_id: str) -> list[ObligationFrontierRow]:
        rows = self.conn.execute(
            "SELECT * FROM obligation_frontier WHERE session_id = ? ORDER BY priority, obligation_id",
            (session_id,),
        ).fetchall()
        return [self._from_row(row) for row in rows]

    @staticmethod
    def _from_row(row: sqlite3.Row) -> ObligationFrontierRow:
        dirty_reasons_raw = row["dirty_reasons_json"]
        dirty_reasons = json.loads(dirty_reasons_raw) if dirty_reasons_raw else []
        return ObligationFrontierRow(
            session_id=row["session_id"],
            obligation_id=row["obligation_id"],
            priority=row["priority"],
            obligation_status=row["obligation_status"],
            dirty=bool(row["dirty"]),
            dirty_reasons=dirty_reasons,
            supported_assertion_count=row["supported_assertion_count"],
            confirmed_assertion_count=row["confirmed_assertion_count"],
            speculative_assertion_count=row["speculative_assertion_count"],
            refuted_assertion_count=row["refuted_assertion_count"],
            live_stale_ticket_count=row["live_stale_ticket_count"],
            recent_failed_family_count=row["recent_failed_family_count"],
            rendered_positive_json=row["rendered_positive_json"],
            rendered_negative_json=row["rendered_negative_json"],
            rendered_uncertainty_json=row["rendered_uncertainty_json"],
            suggested_next_check=row["suggested_next_check"],
            render_hash=row["render_hash"],
            render_version=row["render_version"],
            token_estimate=row["token_estimate"],
            last_rebuilt_at=row["last_rebuilt_at"],
            updated_at=row["updated_at"],
        )

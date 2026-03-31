from __future__ import annotations

import sqlite3

from egtsr_runtime.enums import InvalidationStatus
from egtsr_runtime.models import InvalidationTicket
from egtsr_runtime.repositories._base import dump_json, load_dict


class SqliteInvalidationRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def get(self, ticket_id: str) -> InvalidationTicket | None:
        row = self.conn.execute(
            "SELECT * FROM invalidation_tickets WHERE id = ?",
            (ticket_id,),
        ).fetchone()
        return self._from_row(row) if row is not None else None

    def list_for_session(self, session_id: str) -> list[InvalidationTicket]:
        rows = self.conn.execute(
            "SELECT * FROM invalidation_tickets WHERE session_id = ? ORDER BY created_at, id",
            (session_id,),
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def list_live_for_assertions(self, assertion_ids: list[str]) -> list[InvalidationTicket]:
        if not assertion_ids:
            return []
        placeholders = ",".join("?" for _ in assertion_ids)
        rows = self.conn.execute(
            f"""SELECT * FROM invalidation_tickets
                WHERE subject_type = 'assertion' AND subject_id IN ({placeholders}) AND status = ?
                ORDER BY created_at, id""",  # noqa: S608
            (*assertion_ids, InvalidationStatus.LIVE.value),
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def list_live_for_obligations(self, obligation_ids: list[str]) -> list[InvalidationTicket]:
        if not obligation_ids:
            return []
        placeholders = ",".join("?" for _ in obligation_ids)
        rows = self.conn.execute(
            f"""SELECT * FROM invalidation_tickets
                WHERE subject_type = 'obligation' AND subject_id IN ({placeholders}) AND status = ?
                ORDER BY created_at, id""",  # noqa: S608
            (*obligation_ids, InvalidationStatus.LIVE.value),
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def bulk_upsert(self, tickets: list[InvalidationTicket]) -> None:
        if not tickets:
            return
        for ticket in tickets:
            self.upsert(ticket)

    def list_live_for_session(self, session_id: str) -> list[InvalidationTicket]:
        rows = self.conn.execute(
            "SELECT * FROM invalidation_tickets WHERE session_id = ? AND status = ? ORDER BY created_at, id",
            (session_id, InvalidationStatus.LIVE.value),
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def list_live_for_evidence_ids(self, evidence_ids: list[str]) -> list[InvalidationTicket]:
        if not evidence_ids:
            return []
        placeholders = ",".join("?" for _ in evidence_ids)
        rows = self.conn.execute(
            f"""SELECT * FROM invalidation_tickets
                WHERE subject_type = 'evidence' AND subject_id IN ({placeholders}) AND status = ?
                ORDER BY created_at, id""",  # noqa: S608
            (*evidence_ids, InvalidationStatus.LIVE.value),
        ).fetchall()
        return [self._from_row(row) for row in rows]

    def upsert(self, ticket: InvalidationTicket) -> None:
        self.conn.execute(
            """
            INSERT INTO invalidation_tickets (
                id, session_id, subject_type, subject_id, trigger_kind,
                trigger_ref, status, metadata_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                session_id = excluded.session_id,
                subject_type = excluded.subject_type,
                subject_id = excluded.subject_id,
                trigger_kind = excluded.trigger_kind,
                trigger_ref = excluded.trigger_ref,
                status = excluded.status,
                metadata_json = excluded.metadata_json,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            (
                ticket.id,
                ticket.session_id,
                ticket.subject_type,
                ticket.subject_id,
                ticket.trigger_kind,
                ticket.trigger_ref,
                ticket.status.value,
                dump_json(ticket.metadata),
                ticket.created_at,
                ticket.updated_at,
            ),
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> InvalidationTicket:
        return InvalidationTicket(
            id=row["id"],
            session_id=row["session_id"],
            subject_type=row["subject_type"],
            subject_id=row["subject_id"],
            trigger_kind=row["trigger_kind"],
            trigger_ref=row["trigger_ref"],
            status=InvalidationStatus(row["status"]),
            metadata=load_dict(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

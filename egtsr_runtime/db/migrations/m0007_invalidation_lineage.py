"""0007 — Add caused_by_ticket_id to invalidation_tickets for propagation lineage."""
from __future__ import annotations

import sqlite3

from egtsr_runtime.db.migrations.registry import MigrationSpec

_SQL = """\
ALTER TABLE invalidation_tickets ADD COLUMN caused_by_ticket_id TEXT;

CREATE INDEX IF NOT EXISTS idx_invalidation_tickets_caused_by
    ON invalidation_tickets(caused_by_ticket_id);
CREATE INDEX IF NOT EXISTS idx_invalidation_tickets_subject_type_status
    ON invalidation_tickets(session_id, subject_type, status);
"""


def _up(conn: sqlite3.Connection) -> None:
    for statement in _SQL.strip().split(";"):
        statement = statement.strip()
        if statement:
            conn.execute(statement)


MIGRATION = MigrationSpec(version=7, name="invalidation_lineage", up=_up)

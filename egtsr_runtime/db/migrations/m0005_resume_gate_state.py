"""0005 — resume_gate_state table for DB-authoritative gate decisions."""
from __future__ import annotations

import sqlite3

from egtsr_runtime.db.migrations.registry import MigrationSpec

_SQL = """\
CREATE TABLE IF NOT EXISTS resume_gate_state (
    session_id TEXT PRIMARY KEY,
    edit_blocked INTEGER NOT NULL DEFAULT 0,
    reason TEXT,
    required_rechecks_json TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
"""


def _up(conn: sqlite3.Connection) -> None:
    conn.executescript(_SQL)


MIGRATION = MigrationSpec(version=5, name="resume_gate_state", up=_up)

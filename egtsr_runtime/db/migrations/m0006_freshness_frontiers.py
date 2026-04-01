"""0006 — freshness_frontiers table for repo state freshness tracking."""
from __future__ import annotations

import sqlite3

from egtsr_runtime.db.migrations.registry import MigrationSpec

_SQL = """\
CREATE TABLE IF NOT EXISTS freshness_frontiers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    repo_hash TEXT NOT NULL,
    branch TEXT,
    head_hash TEXT,
    dirty INTEGER NOT NULL DEFAULT 0,
    changed_files_fingerprint TEXT,
    live_ticket_ids_json TEXT NOT NULL DEFAULT '[]',
    open_obligation_ids_json TEXT NOT NULL DEFAULT '[]',
    capsule_id TEXT,
    source TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_freshness_frontiers_session
    ON freshness_frontiers(session_id);
CREATE INDEX IF NOT EXISTS idx_freshness_frontiers_session_source
    ON freshness_frontiers(session_id, source);
"""


def _up(conn: sqlite3.Connection) -> None:
    conn.executescript(_SQL)


MIGRATION = MigrationSpec(version=6, name="freshness_frontiers", up=_up)

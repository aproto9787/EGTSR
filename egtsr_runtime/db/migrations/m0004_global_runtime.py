"""0004 — Global runtime: runtime_projects table."""
from __future__ import annotations

import sqlite3

from egtsr_runtime.db.migrations.registry import MigrationSpec

_SQL = """\
CREATE TABLE IF NOT EXISTS runtime_projects (
    repo_hash TEXT PRIMARY KEY,
    repo_root_canonical TEXT NOT NULL,
    display_name TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_seen_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _up(conn: sqlite3.Connection) -> None:
    conn.executescript(_SQL)


MIGRATION = MigrationSpec(version=4, name="global_runtime_projects", up=_up)

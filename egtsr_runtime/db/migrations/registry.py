"""Migration registry — discovers, orders, and applies versioned migrations."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable


@dataclass(frozen=True, slots=True)
class MigrationSpec:
    version: int
    name: str
    up: Callable[[sqlite3.Connection], None]


def _ensure_schema_migrations_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            applied_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _get_applied_versions(conn: sqlite3.Connection) -> set[int]:
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {row[0] for row in rows}


def _mark_applied(conn: sqlite3.Connection, spec: MigrationSpec) -> None:
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
        (spec.version, spec.name, now),
    )


def _legacy_tables_exist(conn: sqlite3.Connection) -> bool:
    """Detect a pre-registry database that already has canonical tables."""
    row = conn.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='sessions'"
    ).fetchone()
    return row[0] > 0


def _load_all_migrations() -> list[MigrationSpec]:
    from egtsr_runtime.db.migrations.m0001_initial import MIGRATION as m0001
    from egtsr_runtime.db.migrations.m0002_projection_tables import MIGRATION as m0002
    from egtsr_runtime.db.migrations.m0003_targeted_query_indexes import MIGRATION as m0003

    return sorted([m0001, m0002, m0003], key=lambda m: m.version)


def run_registry_migrations(conn: sqlite3.Connection) -> None:
    """Apply all pending migrations to *conn*."""
    _ensure_schema_migrations_table(conn)
    applied = _get_applied_versions(conn)
    all_migrations = _load_all_migrations()

    # Handle pre-existing DB created before the registry existed:
    # if no migrations are recorded but canonical tables are present,
    # mark the initial migration as already applied.
    if not applied and _legacy_tables_exist(conn):
        initial = all_migrations[0]
        _mark_applied(conn, initial)
        conn.commit()
        applied.add(initial.version)

    for spec in all_migrations:
        if spec.version in applied:
            continue
        spec.up(conn)
        _mark_applied(conn, spec)
        conn.commit()

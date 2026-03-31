"""Versioned migration system for EGTSR SQLite database.

Backward-compatible: ``run_migrations(conn)`` still works as before,
but now delegates to the registry-based migration runner.
"""
from __future__ import annotations

import sqlite3

from egtsr_runtime.db.migrations.registry import run_registry_migrations


def run_migrations(conn: sqlite3.Connection) -> None:
    """Run all pending migrations on *conn*.

    Drop-in replacement for the legacy ``schema.sql`` replay.
    """
    run_registry_migrations(conn)

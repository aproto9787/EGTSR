"""SqliteRuntime — boot-once DB manager.

Opens a persistent connection, applies pragmas, runs pending migrations
exactly once, and hands out that connection for UoW usage.
"""
from __future__ import annotations

import sqlite3

from egtsr_runtime.db.connection import get_connection
from egtsr_runtime.db.migrations import run_migrations


class SqliteRuntime:
    """Boot-once SQLite runtime.

    Typical usage (daemon)::

        runtime = SqliteRuntime(paths.db_path)
        conn = runtime.boot()        # migrations run here, once
        ...
        uow = SqliteUnitOfWork(conn)  # no migration, no open
        with uow:
            ...
        ...
        runtime.shutdown()
    """

    def __init__(self, db_path: str) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._booted = False

    @property
    def booted(self) -> bool:
        return self._booted

    def boot(self) -> sqlite3.Connection:
        """Open connection, set pragmas, run migrations. Idempotent."""
        if self._booted:
            return self._conn  # type: ignore[return-value]

        conn = get_connection(self._db_path, check_same_thread=False)
        run_migrations(conn)

        self._conn = conn
        self._booted = True
        return conn

    def connection(self) -> sqlite3.Connection:
        """Return the booted connection. Raises if not booted."""
        if not self._booted or self._conn is None:
            raise RuntimeError("SqliteRuntime has not been booted")
        return self._conn

    def shutdown(self) -> None:
        """Close the persistent connection."""
        if self._conn is not None:
            try:
                if self._conn.in_transaction:
                    self._conn.rollback()
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        self._booted = False

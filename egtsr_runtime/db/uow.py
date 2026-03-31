from __future__ import annotations

import sqlite3
from typing import Any

from egtsr_runtime.config import RuntimeConfig
from egtsr_runtime.db.connection import get_connection
from egtsr_runtime.db.migrations import run_migrations
from egtsr_runtime.models import SessionSnapshot
from egtsr_runtime.paths import RuntimePaths
from egtsr_runtime.repositories import (
    SqliteAssertionRepository,
    SqliteAttemptFamilyRepository,
    SqliteCapsuleRepository,
    SqliteEventRepository,
    SqliteEvidenceRepository,
    SqliteInvalidationRepository,
    SqliteObligationRepository,
    SqliteRepoStateRepository,
    SqliteSessionRepository,
    SqliteVerifyRepository,
)


class SqliteUnitOfWork:
    sessions: SqliteSessionRepository
    obligations: SqliteObligationRepository
    evidence: SqliteEvidenceRepository
    assertions: SqliteAssertionRepository
    invalidations: SqliteInvalidationRepository
    verify_results: SqliteVerifyRepository
    attempt_families: SqliteAttemptFamilyRepository
    capsules: SqliteCapsuleRepository
    events: SqliteEventRepository
    repo_state: SqliteRepoStateRepository

    def __init__(self, db_path: str | RuntimePaths | RuntimeConfig) -> None:
        self.db_path = _resolve_db_path(db_path)
        self.conn: sqlite3.Connection | None = None

    def __enter__(self) -> "SqliteUnitOfWork":
        self.conn = get_connection(self.db_path)
        run_migrations(self.conn)
        self.sessions = SqliteSessionRepository(self.conn)
        self.obligations = SqliteObligationRepository(self.conn)
        self.evidence = SqliteEvidenceRepository(self.conn)
        self.assertions = SqliteAssertionRepository(self.conn)
        self.invalidations = SqliteInvalidationRepository(self.conn)
        self.verify_results = SqliteVerifyRepository(self.conn)
        self.attempt_families = SqliteAttemptFamilyRepository(self.conn)
        self.capsules = SqliteCapsuleRepository(self.conn)
        self.events = SqliteEventRepository(self.conn)
        self.repo_state = SqliteRepoStateRepository(self.conn)
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self.conn is None:
            return
        try:
            if exc_type is not None:
                self.rollback()
            elif self.conn.in_transaction:
                self.rollback()
        finally:
            self.conn.close()
            self.conn = None

    def commit(self) -> None:
        self._require_connection().commit()

    def rollback(self) -> None:
        self._require_connection().rollback()

    def _require_connection(self) -> sqlite3.Connection:
        if self.conn is None:
            raise RuntimeError("Unit of work is not active")
        return self.conn


def save_snapshot(uow: SqliteUnitOfWork, snapshot: SessionSnapshot) -> None:
    existing = uow.sessions.get(snapshot.session.id)
    if existing is None:
        uow.sessions.create(snapshot.session)
    else:
        uow.sessions.update(snapshot.session)

    conn = uow._require_connection()
    if snapshot.repo_state is None:
        conn.execute("DELETE FROM repo_state WHERE session_id = ?", (snapshot.session.id,))
    else:
        uow.repo_state.upsert(snapshot.repo_state)

    conn.execute("DELETE FROM capsules WHERE session_id = ?", (snapshot.session.id,))
    conn.execute("DELETE FROM events WHERE session_id = ?", (snapshot.session.id,))

    for capsule in snapshot.capsules:
        uow.capsules.create(capsule)
    for event in snapshot.events:
        uow.events.create(event)


def load_snapshot(uow: SqliteUnitOfWork, session_id: str) -> SessionSnapshot | None:
    session = uow.sessions.get(session_id)
    if session is None:
        return None
    return SessionSnapshot(
        session=session,
        repo_state=uow.repo_state.get(session_id),
        capsules=uow.capsules.list_for_session(session_id),
        events=uow.events.list_for_session(session_id),
    )


def _resolve_db_path(db_path: str | RuntimePaths | RuntimeConfig) -> str:
    if isinstance(db_path, str):
        return db_path
    if isinstance(db_path, RuntimePaths):
        return db_path.db_path
    if isinstance(db_path, RuntimeConfig):
        return db_path.db_path
    raise TypeError(f"Unsupported db path source: {type(db_path)!r}")

from __future__ import annotations

import sqlite3
from typing import Any

from egtsr_runtime.config import RuntimeConfig
from egtsr_runtime.db.connection import get_connection
from egtsr_runtime.db.migrations import run_migrations
from egtsr_runtime.models import SessionSnapshot
from egtsr_runtime.paths import RuntimePaths
from egtsr_runtime.repositories import (
    SqliteAssertionEvidenceLinkRepository,
    SqliteAssertionRepository,
    SqliteAttemptFamilyRepository,
    SqliteCapsuleRepository,
    SqliteEventRepository,
    SqliteEvidenceRepository,
    SqliteInvalidationRepository,
    SqliteObligationFrontierRepository,
    SqliteObligationRepository,
    SqlitePathSubjectIndexRepository,
    SqliteRepoStateRepository,
    SqliteSessionFrontierRepository,
    SqliteSessionRepository,
    SqliteVerifyRepository,
)


class SqliteUnitOfWork:
    """Unit-of-work over a SQLite connection.

    Two modes:

    **Legacy** (backward-compatible) — pass a path / RuntimePaths / RuntimeConfig::

        with SqliteUnitOfWork(config) as uow:
            ...  # opens connection, runs migrations, closes on exit

    **Booted** — pass a ``sqlite3.Connection`` that was already opened and
    migrated by :class:`~egtsr_runtime.db.runtime.SqliteRuntime`::

        uow = SqliteUnitOfWork(conn)
        with uow:
            ...  # transaction only; connection stays open after exit
    """

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
    # Projection repositories
    path_subject_index: SqlitePathSubjectIndexRepository
    assertion_evidence_links: SqliteAssertionEvidenceLinkRepository
    obligation_frontier: SqliteObligationFrontierRepository
    session_frontier: SqliteSessionFrontierRepository

    def __init__(
        self, source: str | RuntimePaths | RuntimeConfig | sqlite3.Connection
    ) -> None:
        if isinstance(source, sqlite3.Connection):
            self.db_path: str | None = None
            self.conn: sqlite3.Connection | None = source
            self._owns_connection = False
        else:
            self.db_path = _resolve_db_path(source)
            self.conn = None
            self._owns_connection = True

    def __enter__(self) -> "SqliteUnitOfWork":
        if self._owns_connection:
            self.conn = get_connection(self.db_path)  # type: ignore[arg-type]
            run_migrations(self.conn)

        self._init_repositories()
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
            if self._owns_connection:
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

    def _init_repositories(self) -> None:
        conn = self._require_connection()
        self.sessions = SqliteSessionRepository(conn)
        self.obligations = SqliteObligationRepository(conn)
        self.evidence = SqliteEvidenceRepository(conn)
        self.assertions = SqliteAssertionRepository(conn)
        self.invalidations = SqliteInvalidationRepository(conn)
        self.verify_results = SqliteVerifyRepository(conn)
        self.attempt_families = SqliteAttemptFamilyRepository(conn)
        self.capsules = SqliteCapsuleRepository(conn)
        self.events = SqliteEventRepository(conn)
        self.repo_state = SqliteRepoStateRepository(conn)
        # Projection repositories
        self.path_subject_index = SqlitePathSubjectIndexRepository(conn)
        self.assertion_evidence_links = SqliteAssertionEvidenceLinkRepository(conn)
        self.obligation_frontier = SqliteObligationFrontierRepository(conn)
        self.session_frontier = SqliteSessionFrontierRepository(conn)


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

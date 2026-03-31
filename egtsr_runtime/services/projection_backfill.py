"""Projection backfill / rebuild service.

Rebuilds all four projection tables from canonical data.
Idempotent: clears projection tables first, then re-populates.
Can operate on a single session or all sessions.
"""
from __future__ import annotations

import sqlite3

from egtsr_runtime.services.projections import (
    on_assertion_upsert,
    on_attempt_family_upsert,
    on_evidence_create,
    on_obligation_upsert,
    sync_session_frontier,
)
from egtsr_runtime.repositories.assertions import SqliteAssertionRepository
from egtsr_runtime.repositories.attempt_families import SqliteAttemptFamilyRepository
from egtsr_runtime.repositories.evidence import SqliteEvidenceRepository
from egtsr_runtime.repositories.obligations import SqliteObligationRepository


def _clear_projections(conn: sqlite3.Connection, session_id: str | None = None) -> None:
    """Delete projection rows, optionally scoped to a session."""
    tables = [
        "assertion_evidence_links",
        "path_subject_index",
        "obligation_frontier",
        "session_frontier",
    ]
    for table in tables:
        if session_id is not None:
            conn.execute(f"DELETE FROM {table} WHERE session_id = ?", (session_id,))  # noqa: S608
        else:
            conn.execute(f"DELETE FROM {table}")  # noqa: S608


def rebuild_session_projections(conn: sqlite3.Connection, session_id: str) -> None:
    """Rebuild all projections for a single session. Idempotent."""
    _clear_projections(conn, session_id)

    obligations_repo = SqliteObligationRepository(conn)
    assertions_repo = SqliteAssertionRepository(conn)
    evidence_repo = SqliteEvidenceRepository(conn)
    families_repo = SqliteAttemptFamilyRepository(conn)

    # 1. Obligations -> obligation_frontier
    for obligation in obligations_repo.list_for_session(session_id):
        on_obligation_upsert(conn, obligation)

    # 2. Evidence -> path_subject_index
    for evidence in evidence_repo.list_for_session(session_id):
        on_evidence_create(conn, evidence)

    # 3. Assertions -> assertion_evidence_links + path_subject_index + obligation_frontier counts
    for assertion in assertions_repo.list_for_session(session_id):
        on_assertion_upsert(conn, assertion)

    # 4. Attempt families -> path_subject_index + obligation_frontier counts
    for family in families_repo.list_for_session(session_id):
        on_attempt_family_upsert(conn, family)

    # 5. Session frontier
    sync_session_frontier(conn, session_id)


def rebuild_projections(conn: sqlite3.Connection) -> None:
    """Rebuild all projections for all sessions. Idempotent."""
    _clear_projections(conn)

    session_ids = [
        row["id"]
        for row in conn.execute("SELECT id FROM sessions ORDER BY created_at").fetchall()
    ]

    for session_id in session_ids:
        # We already cleared globally, no need to clear per-session
        obligations_repo = SqliteObligationRepository(conn)
        assertions_repo = SqliteAssertionRepository(conn)
        evidence_repo = SqliteEvidenceRepository(conn)
        families_repo = SqliteAttemptFamilyRepository(conn)

        for obligation in obligations_repo.list_for_session(session_id):
            on_obligation_upsert(conn, obligation)

        for evidence in evidence_repo.list_for_session(session_id):
            on_evidence_create(conn, evidence)

        for assertion in assertions_repo.list_for_session(session_id):
            on_assertion_upsert(conn, assertion)

        for family in families_repo.list_for_session(session_id):
            on_attempt_family_upsert(conn, family)

        sync_session_frontier(conn, session_id)

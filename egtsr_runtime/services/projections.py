"""Projection maintenance service.

Keeps the four projection tables in sync with canonical writes
within the same transaction (dual-write, per doc 04 principle 3).

Tables maintained:
- assertion_evidence_links
- path_subject_index
- obligation_frontier
- session_frontier
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone

from egtsr_runtime.enums import AssertionStatus, ObligationStatus
from egtsr_runtime.models import (
    Assertion,
    AttemptFamily,
    Evidence,
    InvalidationTicket,
    Obligation,
)
from egtsr_runtime.utils.paths import normalize_path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# assertion_evidence_links
# ---------------------------------------------------------------------------

def sync_assertion_evidence_links(
    conn: sqlite3.Connection,
    assertion: Assertion,
) -> None:
    """Rebuild links for a single assertion from its evidence_ids list."""
    now = _now()
    conn.execute(
        "DELETE FROM assertion_evidence_links WHERE assertion_id = ?",
        (assertion.id,),
    )
    for eid in assertion.evidence_ids:
        conn.execute(
            """INSERT OR IGNORE INTO assertion_evidence_links
               (session_id, assertion_id, evidence_id, created_at)
               VALUES (?, ?, ?, ?)""",
            (assertion.session_id, assertion.id, eid, now),
        )


# ---------------------------------------------------------------------------
# path_subject_index
# ---------------------------------------------------------------------------

def _upsert_path_index(
    conn: sqlite3.Connection,
    session_id: str,
    path: str,
    subject_type: str,
    subject_id: str,
    role: str,
) -> None:
    normalized = normalize_path(path)
    if not normalized:
        return
    now = _now()
    conn.execute(
        """INSERT INTO path_subject_index
           (session_id, normalized_path, subject_type, subject_id, role, updated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(session_id, normalized_path, subject_type, subject_id, role)
           DO UPDATE SET updated_at = excluded.updated_at""",
        (session_id, normalized, subject_type, subject_id, role, now),
    )


def sync_assertion_path_index(
    conn: sqlite3.Connection,
    assertion: Assertion,
) -> None:
    """Update path_subject_index for an assertion's scope_ref."""
    # Remove old entries for this assertion
    conn.execute(
        "DELETE FROM path_subject_index WHERE subject_type = 'assertion' AND subject_id = ?",
        (assertion.id,),
    )
    if assertion.scope_ref:
        _upsert_path_index(
            conn,
            assertion.session_id,
            assertion.scope_ref,
            "assertion",
            assertion.id,
            "assertion.scope_ref",
        )


def sync_evidence_path_index(
    conn: sqlite3.Connection,
    evidence: Evidence,
) -> None:
    """Update path_subject_index for an evidence's path and scope_ref."""
    conn.execute(
        "DELETE FROM path_subject_index WHERE subject_type = 'evidence' AND subject_id = ?",
        (evidence.id,),
    )
    if evidence.path:
        _upsert_path_index(
            conn,
            evidence.session_id,
            evidence.path,
            "evidence",
            evidence.id,
            "evidence.path",
        )
    if evidence.scope_ref:
        _upsert_path_index(
            conn,
            evidence.session_id,
            evidence.scope_ref,
            "evidence",
            evidence.id,
            "evidence.scope_ref",
        )


def sync_attempt_family_path_index(
    conn: sqlite3.Connection,
    family: AttemptFamily,
) -> None:
    """Update path_subject_index for an attempt family's touched_scope."""
    conn.execute(
        "DELETE FROM path_subject_index WHERE subject_type = 'attempt_family' AND subject_id = ?",
        (family.id,),
    )
    for scope in family.touched_scope:
        if isinstance(scope, str):
            _upsert_path_index(
                conn,
                family.session_id,
                scope,
                "attempt_family",
                family.id,
                "attempt_family.touched_scope",
            )


# ---------------------------------------------------------------------------
# obligation_frontier
# ---------------------------------------------------------------------------

def sync_obligation_frontier(
    conn: sqlite3.Connection,
    obligation: Obligation,
    dirty_reason: str = "obligation_changed",
) -> None:
    """Upsert obligation_frontier row, marking dirty."""
    now = _now()
    existing = conn.execute(
        "SELECT dirty_reasons_json FROM obligation_frontier WHERE obligation_id = ?",
        (obligation.id,),
    ).fetchone()

    if existing is not None:
        reasons = json.loads(existing["dirty_reasons_json"]) if existing["dirty_reasons_json"] else []
        if dirty_reason not in reasons:
            reasons.append(dirty_reason)
        conn.execute(
            """UPDATE obligation_frontier SET
               priority = ?, obligation_status = ?, dirty = 1,
               dirty_reasons_json = ?, updated_at = ?
               WHERE obligation_id = ?""",
            (
                obligation.priority,
                obligation.status.value,
                json.dumps(reasons),
                now,
                obligation.id,
            ),
        )
    else:
        conn.execute(
            """INSERT INTO obligation_frontier
               (session_id, obligation_id, priority, obligation_status,
                dirty, dirty_reasons_json, updated_at)
               VALUES (?, ?, ?, ?, 1, ?, ?)""",
            (
                obligation.session_id,
                obligation.id,
                obligation.priority,
                obligation.status.value,
                json.dumps([dirty_reason]),
                now,
            ),
        )


def mark_obligation_frontier_dirty(
    conn: sqlite3.Connection,
    obligation_id: str,
    reason: str,
) -> None:
    """Mark an existing obligation frontier row as dirty."""
    now = _now()
    existing = conn.execute(
        "SELECT dirty_reasons_json FROM obligation_frontier WHERE obligation_id = ?",
        (obligation_id,),
    ).fetchone()
    if existing is None:
        return
    reasons = json.loads(existing["dirty_reasons_json"]) if existing["dirty_reasons_json"] else []
    if reason not in reasons:
        reasons.append(reason)
    conn.execute(
        "UPDATE obligation_frontier SET dirty = 1, dirty_reasons_json = ?, updated_at = ? WHERE obligation_id = ?",
        (json.dumps(reasons), now, obligation_id),
    )


def recount_obligation_frontier(
    conn: sqlite3.Connection,
    obligation_id: str,
) -> None:
    """Recount assertion status counts for an obligation frontier row."""
    row = conn.execute(
        "SELECT session_id FROM obligation_frontier WHERE obligation_id = ?",
        (obligation_id,),
    ).fetchone()
    if row is None:
        return

    session_id = row["session_id"]
    counts = conn.execute(
        """SELECT
            SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) as supported,
            SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) as confirmed,
            SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) as speculative,
            SUM(CASE WHEN status = ? THEN 1 ELSE 0 END) as refuted
           FROM assertions
           WHERE session_id = ? AND obligation_id = ?""",
        (
            AssertionStatus.SUPPORTED.value,
            AssertionStatus.CONFIRMED.value,
            AssertionStatus.SPECULATIVE.value,
            AssertionStatus.REFUTED.value,
            session_id,
            obligation_id,
        ),
    ).fetchone()

    stale_count = conn.execute(
        """SELECT COUNT(*) FROM invalidation_tickets
           WHERE session_id = ? AND subject_type = 'obligation'
           AND subject_id = ? AND status = ?""",
        (session_id, obligation_id, "live"),
    ).fetchone()[0]

    # Count assertion-level stale tickets too
    assertion_stale = conn.execute(
        """SELECT COUNT(*) FROM invalidation_tickets it
           JOIN assertions a ON it.subject_id = a.id
           WHERE it.session_id = ? AND it.subject_type = 'assertion'
           AND a.obligation_id = ? AND it.status = ?""",
        (session_id, obligation_id, "live"),
    ).fetchone()[0]

    failed_families = conn.execute(
        """SELECT COUNT(*) FROM attempt_families
           WHERE session_id = ? AND obligation_id = ? AND last_outcome = 'fail'""",
        (session_id, obligation_id),
    ).fetchone()[0]

    now = _now()
    conn.execute(
        """UPDATE obligation_frontier SET
           supported_assertion_count = ?,
           confirmed_assertion_count = ?,
           speculative_assertion_count = ?,
           refuted_assertion_count = ?,
           live_stale_ticket_count = ?,
           recent_failed_family_count = ?,
           updated_at = ?
           WHERE obligation_id = ?""",
        (
            counts["supported"] or 0,
            counts["confirmed"] or 0,
            counts["speculative"] or 0,
            counts["refuted"] or 0,
            stale_count + assertion_stale,
            failed_families or 0,
            now,
            obligation_id,
        ),
    )


# ---------------------------------------------------------------------------
# session_frontier
# ---------------------------------------------------------------------------

def sync_session_frontier(
    conn: sqlite3.Connection,
    session_id: str,
) -> None:
    """Upsert session_frontier with current dirty obligation count."""
    now = _now()
    dirty_count = conn.execute(
        "SELECT COUNT(*) FROM obligation_frontier WHERE session_id = ? AND dirty = 1",
        (session_id,),
    ).fetchone()[0]

    conn.execute(
        """INSERT INTO session_frontier
           (session_id, dirty_obligation_count, updated_at)
           VALUES (?, ?, ?)
           ON CONFLICT(session_id)
           DO UPDATE SET
             dirty_obligation_count = excluded.dirty_obligation_count,
             frontier_version = frontier_version + 1,
             updated_at = excluded.updated_at""",
        (session_id, dirty_count, now),
    )


def increment_session_frontier_version(
    conn: sqlite3.Connection,
    session_id: str,
    dirty_reason: str = "repo_state_changed",
) -> None:
    """Increment session_frontier version (e.g. on repo_state change)."""
    now = _now()
    conn.execute(
        """INSERT INTO session_frontier
           (session_id, frontier_version, dirty_obligation_count, updated_at)
           VALUES (?, 1, 0, ?)
           ON CONFLICT(session_id)
           DO UPDATE SET
             frontier_version = frontier_version + 1,
             updated_at = excluded.updated_at""",
        (session_id, now),
    )


# ---------------------------------------------------------------------------
# Composite sync (called on canonical writes)
# ---------------------------------------------------------------------------

def on_obligation_upsert(conn: sqlite3.Connection, obligation: Obligation) -> None:
    """Projection sync after obligation upsert."""
    sync_obligation_frontier(conn, obligation, "obligation_changed")
    sync_session_frontier(conn, obligation.session_id)


def on_assertion_upsert(conn: sqlite3.Connection, assertion: Assertion) -> None:
    """Projection sync after assertion upsert."""
    sync_assertion_evidence_links(conn, assertion)
    sync_assertion_path_index(conn, assertion)
    if assertion.obligation_id:
        mark_obligation_frontier_dirty(conn, assertion.obligation_id, "assertion_changed")
        recount_obligation_frontier(conn, assertion.obligation_id)
    sync_session_frontier(conn, assertion.session_id)


def on_evidence_create(conn: sqlite3.Connection, evidence: Evidence) -> None:
    """Projection sync after evidence create."""
    sync_evidence_path_index(conn, evidence)
    # Evidence alone doesn't dirty obligation frontier per spec:
    # "evidence가 아직 assertion과 연결되지 않았다면 obligation frontier는 즉시 dirty 필요 없음"


def on_invalidation_upsert(
    conn: sqlite3.Connection,
    ticket: InvalidationTicket,
) -> None:
    """Projection sync after invalidation ticket upsert."""
    if ticket.subject_type == "obligation":
        mark_obligation_frontier_dirty(conn, ticket.subject_id, "invalidation_changed")
        recount_obligation_frontier(conn, ticket.subject_id)
    elif ticket.subject_type == "assertion":
        # Find the assertion's obligation and dirty it
        row = conn.execute(
            "SELECT obligation_id, session_id FROM assertions WHERE id = ?",
            (ticket.subject_id,),
        ).fetchone()
        if row and row["obligation_id"]:
            mark_obligation_frontier_dirty(conn, row["obligation_id"], "invalidation_changed")
            recount_obligation_frontier(conn, row["obligation_id"])


def on_attempt_family_upsert(
    conn: sqlite3.Connection,
    family: AttemptFamily,
) -> None:
    """Projection sync after attempt family upsert."""
    sync_attempt_family_path_index(conn, family)
    if family.obligation_id:
        mark_obligation_frontier_dirty(conn, family.obligation_id, "attempt_family_changed")
        recount_obligation_frontier(conn, family.obligation_id)
    sync_session_frontier(conn, family.session_id)


def on_repo_state_change(conn: sqlite3.Connection, session_id: str) -> None:
    """Projection sync after repo_state change."""
    increment_session_frontier_version(conn, session_id, "repo_state_changed")

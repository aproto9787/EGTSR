"""0002 — Projection tables for hot-path queries (Step 03 backfill)."""
from __future__ import annotations

import sqlite3

from egtsr_runtime.db.migrations.registry import MigrationSpec

_SQL = """\
CREATE TABLE IF NOT EXISTS assertion_evidence_links (
    session_id TEXT NOT NULL,
    assertion_id TEXT NOT NULL,
    evidence_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (assertion_id, evidence_id),
    FOREIGN KEY (assertion_id) REFERENCES assertions(id),
    FOREIGN KEY (evidence_id) REFERENCES evidence(id)
);

CREATE INDEX IF NOT EXISTS idx_ael_session_assertion
  ON assertion_evidence_links(session_id, assertion_id);

CREATE INDEX IF NOT EXISTS idx_ael_session_evidence
  ON assertion_evidence_links(session_id, evidence_id);

CREATE TABLE IF NOT EXISTS path_subject_index (
    session_id TEXT NOT NULL,
    normalized_path TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    role TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (session_id, normalized_path, subject_type, subject_id, role)
);

CREATE INDEX IF NOT EXISTS idx_path_subject_lookup
  ON path_subject_index(session_id, normalized_path, subject_type);

CREATE INDEX IF NOT EXISTS idx_path_subject_subject
  ON path_subject_index(session_id, subject_type, subject_id);

CREATE TABLE IF NOT EXISTS obligation_frontier (
    session_id TEXT NOT NULL,
    obligation_id TEXT PRIMARY KEY,
    priority INTEGER NOT NULL,
    obligation_status TEXT NOT NULL,
    dirty INTEGER NOT NULL DEFAULT 1,
    dirty_reasons_json TEXT NOT NULL DEFAULT '[]',
    supported_assertion_count INTEGER NOT NULL DEFAULT 0,
    confirmed_assertion_count INTEGER NOT NULL DEFAULT 0,
    speculative_assertion_count INTEGER NOT NULL DEFAULT 0,
    refuted_assertion_count INTEGER NOT NULL DEFAULT 0,
    live_stale_ticket_count INTEGER NOT NULL DEFAULT 0,
    recent_failed_family_count INTEGER NOT NULL DEFAULT 0,
    rendered_positive_json TEXT NOT NULL DEFAULT '[]',
    rendered_negative_json TEXT NOT NULL DEFAULT '[]',
    rendered_uncertainty_json TEXT NOT NULL DEFAULT '[]',
    suggested_next_check TEXT,
    render_hash TEXT,
    render_version INTEGER NOT NULL DEFAULT 0,
    token_estimate INTEGER NOT NULL DEFAULT 0,
    last_rebuilt_at TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (obligation_id) REFERENCES obligations(id)
);

CREATE INDEX IF NOT EXISTS idx_obligation_frontier_dirty
  ON obligation_frontier(session_id, dirty, obligation_status, priority);

CREATE TABLE IF NOT EXISTS session_frontier (
    session_id TEXT PRIMARY KEY,
    frontier_version INTEGER NOT NULL DEFAULT 0,
    dirty_obligation_count INTEGER NOT NULL DEFAULT 0,
    last_compiled_capsule_id TEXT,
    last_frontier_hash TEXT,
    last_compiled_at TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);
"""


def _up(conn: sqlite3.Connection) -> None:
    conn.executescript(_SQL)


MIGRATION = MigrationSpec(version=2, name="projection_tables", up=_up)

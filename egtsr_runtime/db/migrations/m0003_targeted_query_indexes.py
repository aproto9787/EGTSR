"""0003 — Additional indexes for targeted queries (Step 04)."""
from __future__ import annotations

import sqlite3

from egtsr_runtime.db.migrations.registry import MigrationSpec

_SQL = """\
CREATE INDEX IF NOT EXISTS idx_obligations_session_status
  ON obligations(session_id, status);

CREATE INDEX IF NOT EXISTS idx_assertions_obligation
  ON assertions(obligation_id);

CREATE INDEX IF NOT EXISTS idx_assertions_session_obligation
  ON assertions(session_id, obligation_id, status);

CREATE INDEX IF NOT EXISTS idx_attempt_families_session_sig
  ON attempt_families(session_id, signature);

CREATE INDEX IF NOT EXISTS idx_invalidation_subject
  ON invalidation_tickets(subject_type, subject_id, status);

CREATE INDEX IF NOT EXISTS idx_invalidation_session_subject
  ON invalidation_tickets(session_id, subject_type, subject_id, status);

CREATE INDEX IF NOT EXISTS idx_attempt_families_obligation_outcome
  ON attempt_families(obligation_id, last_outcome, updated_at);
"""


def _up(conn: sqlite3.Connection) -> None:
    conn.executescript(_SQL)


MIGRATION = MigrationSpec(version=3, name="targeted_query_indexes", up=_up)

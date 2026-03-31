CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    repo_root TEXT NOT NULL,
    branch TEXT,
    head_hash TEXT,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS repo_state (
    session_id TEXT PRIMARY KEY,
    head_hash TEXT,
    dirty INTEGER NOT NULL DEFAULT 0,
    changed_files_json TEXT NOT NULL DEFAULT '[]',
    last_scan_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS obligations (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    source TEXT NOT NULL,
    statement TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 50,
    status TEXT NOT NULL,
    acceptance_check TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS evidence (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    source_tool TEXT NOT NULL,
    path TEXT,
    scope_kind TEXT,
    scope_ref TEXT,
    file_hash TEXT,
    polarity TEXT NOT NULL DEFAULT 'positive',
    excerpt TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS assertions (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    obligation_id TEXT,
    statement TEXT NOT NULL,
    scope_kind TEXT,
    scope_ref TEXT,
    status TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.5,
    evidence_ids_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    FOREIGN KEY (obligation_id) REFERENCES obligations(id)
);

CREATE TABLE IF NOT EXISTS invalidation_tickets (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    subject_type TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    trigger_kind TEXT NOT NULL,
    trigger_ref TEXT,
    status TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS attempt_families (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    obligation_id TEXT,
    signature TEXT NOT NULL,
    touched_scope_json TEXT NOT NULL DEFAULT '[]',
    fail_count INTEGER NOT NULL DEFAULT 1,
    last_outcome TEXT NOT NULL,
    summary TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id),
    FOREIGN KEY (obligation_id) REFERENCES obligations(id)
);

CREATE TABLE IF NOT EXISTS verify_results (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    outcome TEXT NOT NULL,
    affected_obligation_ids_json TEXT NOT NULL DEFAULT '[]',
    excerpt TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS capsules (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    frontier_hash TEXT NOT NULL,
    content TEXT NOT NULL,
    token_count INTEGER NOT NULL,
    audit_pass INTEGER NOT NULL,
    audit_report_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(id)
);

CREATE INDEX IF NOT EXISTS idx_obligations_session ON obligations(session_id);
CREATE INDEX IF NOT EXISTS idx_evidence_session ON evidence(session_id);
CREATE INDEX IF NOT EXISTS idx_assertions_session ON assertions(session_id);
CREATE INDEX IF NOT EXISTS idx_invalidation_tickets_session ON invalidation_tickets(session_id);
CREATE INDEX IF NOT EXISTS idx_attempt_families_session ON attempt_families(session_id);
CREATE INDEX IF NOT EXISTS idx_attempt_families_signature ON attempt_families(signature);
CREATE INDEX IF NOT EXISTS idx_verify_results_session ON verify_results(session_id);
CREATE INDEX IF NOT EXISTS idx_capsules_session ON capsules(session_id);
CREATE INDEX IF NOT EXISTS idx_events_session ON events(session_id);

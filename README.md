# EGTSR

**Task state control, not memory, for Claude Code**

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue)](#requirements)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](./LICENSE)
[![Tests: 164](https://img.shields.io/badge/tests-164-brightgreen)](#benchmarks)

## What is EGTSR?

EGTSR (Execution-Grounded Task-State Runtime) is a Claude Code plugin that prevents unsafe edits and stale continuity illusions by replacing transcript-dependent continuity with explicit task state. In long sessions, compacting can drop critical state, stale evidence can survive file changes, and the agent can repeat the same failing path with false confidence. EGTSR solves this with an obligation-first, freshness-gated, SQLite-backed runtime that compiles a decision capsule on every prompt and blocks unsafe continuation until the state is revalidated.

## Quick Start

```bash
# Primary path: install from Claude Code marketplace
/plugin install egtsr@aproto9787-egtsr
```

Marketplace install is the primary path. It packages the plugin entry, MCP server, hooks, and skills together for Claude Code.

## How It Works

- **SessionStart** bootstraps the session and evaluates resume safety.
- **UserPromptSubmit** compiles a fresh decision capsule on every prompt.
- **PostToolUse** normalizes tool output into evidence and quarantines stale state after file changes.
- **SessionEnd** saves the snapshot used for safe resume.
- **Freshness gate** blocks edit flows until required rechecks pass.

```text
SessionStart ───────────────┐
                            │
UserPromptSubmit ──┐        │
                   ├─> evidence + obligations ─> decision capsule ─> freshness gate ─> CONTINUE / BLOCK
PostToolUse ───────┘                 ▲                     │
                                     │                     └─ stale evidence quarantined on file changes
SessionEnd ──────────────────────────┴─ snapshot + resume artifacts
```

## CLI Commands

```text
egtsr setup          # Register hooks in project (legacy/manual install)
egtsr doctor         # Diagnose runtime health
egtsr inspect        # Inspect session state
egtsr benchmark      # Run benchmark harness
egtsr uninstall      # Remove hooks (legacy/manual install)
```

## MCP Tools (for Claude)

- `egtsr_inspect_obligations`
- `egtsr_inspect_stale`
- `egtsr_inspect_capsule`
- `egtsr_resume_status`
- `egtsr_doctor`
- `egtsr_session_summary`

## Skills

- `/egtsr-setup`
- `/egtsr-status`
- `/egtsr-inspect`
- `/egtsr-doctor`

## Benchmarks

| Scenario | Raw | EGTSR | Savings |
|----------|-----|-------|---------|
| Forced Split | 838 tok | 217 tok | 74% |
| Stale Injection | 945 tok | 172 tok | 82% |
| Repeated Failure | 472 tok | 175 tok | 63% |

Hook latency: ~70ms avg per call. Go/No-Go verdict: CONTINUE.

## Architecture

```text
egtsr_runtime/
  compiler/     Decision capsule compiler + audit
  db/           SQLite storage + UoW pattern
  hooks/        4 Claude Code hook handlers
  ingest/       Tool result normalization
  models/       Domain models (obligation, evidence, assertion, ...)
  mcp/          Read-only inspection service
  ops/          Logging, metrics, health, recovery
  services/     Invalidation, resume gate, verify, attempt families
  ui/           Local read-only inspector
  cli/          CLI entry points
mcp_server/     MCP JSON-RPC server for Claude Code plugin
```

## Implementation Steps (completed)

- [x] Step 00 Foundation Freeze
- [x] Step 01 Domain State + SQLite
- [x] Step 02 Hook Envelope + Session Bootstrap
- [x] Step 03 Decision Capsule Compiler
- [x] Step 04 Compile Audit + Prompt Gate
- [x] Step 05 PostToolUse Ingest + Evidence Normalization
- [x] Step 06 File-Touch Invalidation + Stale Quarantine
- [x] Step 07 Resume Handshake + SessionEnd Snapshot
- [x] Step 08 Verify Results + Attempt Families
- [x] Step 09 MCP Skills + Local Operator UI
- [x] Step 10 Observability + Recovery + Packaging
- [x] Step 11 Benchmark Harness + Go/No-Go

## Requirements

- Python >= 3.12
- No external dependencies (stdlib only)

## Legacy / Manual Install

Use this path only if you are not installing through the Claude Code marketplace.

```bash
pip install .
cd ~/your-project
egtsr setup
```

This manual flow registers EGTSR hooks in the project and keeps the older local-install workflow available.

## License

MIT

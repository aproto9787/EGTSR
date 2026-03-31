---
name: egtsr-inspect
description: Detailed inspection of EGTSR session state — obligations, stale queue, decision capsule, verify results.
user-invocable: true
---

# EGTSR Inspect

Perform detailed inspection of EGTSR session state.

## Usage
The user may specify what to inspect:
- "obligations" — open and verified obligations with evidence counts
- "stale" — invalidation tickets grouped by status
- "capsule" — latest decision capsule content and audit report
- "resume" — resume gate status and blocking conditions
- "all" — everything above

## Steps
1. Determine what the user wants to inspect (default: "all")
2. Find the current session ID from `.egtsr/session.db`
3. Call the appropriate MCP tools:
   - `egtsr_inspect_obligations` for obligations
   - `egtsr_inspect_stale` for stale queue
   - `egtsr_inspect_capsule` for capsule
   - `egtsr_resume_status` for resume gate
4. Present results in a readable format

## Notes
- All operations are read-only
- No state mutations from inspection

---
name: egtsr-status
description: Show current EGTSR session status — open obligations, stale tickets, last capsule audit, resume gate state.
user-invocable: true
---

# EGTSR Status

Show a quick overview of the current EGTSR session state.

## Steps
1. Find the current session ID from `.egtsr/session.db`
2. Use the `egtsr_session_summary` MCP tool with the session ID
3. Present a concise summary to the user:
   - Open obligations count and list
   - Stale ticket count
   - Last capsule audit status (pass/fail)
   - Resume gate state (edit blocked or not)
   - Required rechecks if any

## Output Format
Present as a clean status report, highlighting any issues that need attention.

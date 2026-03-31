---
name: egtsr-setup
description: Activate EGTSR runtime in the current project. Marketplace installs auto-apply plugin assets; manual setup remains for legacy/local installs.
user-invocable: true
---

# EGTSR Setup

If EGTSR was installed via the Claude Code marketplace plugin, hooks/MCP/skills are applied automatically.

Use the steps below only for **Legacy / Manual mode** (local install without marketplace packaging).

## Legacy / Manual mode steps
1. Run `python3 -m egtsr_runtime.cli.main setup --project-dir .` to register hooks
2. Verify `.egtsr/` directory was created
3. Verify `.egtsr/session.db` exists
4. Report setup status to user

## Expected Result
- `.egtsr/` directory with `session.db`, `raw_events/`, `debug/`, `reports/`
- Hooks registered in `.claude/settings.local.json` (legacy/manual mode only)
- EGTSR is now active for this project

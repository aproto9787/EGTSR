---
name: egtsr-setup
description: Activate EGTSR runtime in the current project. Creates .egtsr/ directory and initializes the session database.
user-invocable: true
---

# EGTSR Setup

Initialize EGTSR in the current project directory.

## Steps
1. Run `python3 -m egtsr_runtime.cli.main setup --project-dir .` to register hooks
2. Verify `.egtsr/` directory was created
3. Verify `.egtsr/session.db` exists
4. Report setup status to user

## Expected Result
- `.egtsr/` directory with `session.db`, `raw_events/`, `debug/`, `reports/`
- Hooks registered in `.claude/settings.local.json`
- EGTSR is now active for this project

---
name: egtsr-doctor
description: Diagnose EGTSR runtime health — check DB integrity, artifact existence, hook configuration.
user-invocable: true
---

# EGTSR Doctor

Run health diagnostics on the EGTSR runtime.

## Steps
1. Use the `egtsr_doctor` MCP tool with the current project directory
2. Report findings:
   - DB health (readable, schema valid)
   - Resume gate artifact (exists, valid JSON)
   - Last good capsule artifact (exists, valid JSON)
   - Directory structure (.egtsr/ intact)
   - Log file (writable)
3. For any issues found, suggest remediation steps

## Safety
- Doctor performs read-only checks only
- No unsafe unblock or force operations
- No direct DB modifications

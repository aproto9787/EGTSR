# EGTSR Claude Code Plugin Implementation Plan

## Overview

Transform EGTSR from a pip package + hooks setup into a native Claude Code plugin.
The plugin enables Claude to directly query EGTSR state via MCP tools, while hooks continue
to track session state in the background.

## Current State vs Plugin Target

| Aspect | Current (pip + hooks) | Target (Claude Code Plugin) |
|--------|----------------------|----------------------------|
| Install | `pip install . && egtsr setup` | `claude plugin add egtsr` |
| Interface | hooks (stdin/stdout JSON) | **MCP server** + skills + hooks |
| Commands | CLI (`egtsr doctor`) | **`/egtsr` skills** (in-session) |
| Distribution | PyPI / git clone | **Plugin marketplace** |
| State query | CLI / localhost UI | **Claude calls MCP tools directly** |
| Claude awareness | None (hooks run silently) | **Claude reads obligation/stale/capsule state** |

## Key Value Proposition

Current: Claude is unaware of EGTSR state — hooks run silently behind the scenes.
Plugin: Claude can directly read EGTSR state — "3 obligations open, 1 stale" self-reported.

---

## Plugin Structure

```
egtsr-plugin/
├── .claude-plugin/
│   └── plugin.json                # Plugin manifest
├── egtsr_runtime/                 # Core runtime (existing code)
│   ├── compiler/
│   ├── db/
│   ├── hooks/
│   ├── ingest/
│   ├── mcp/                       # Existing InspectService + handlers
│   ├── models/
│   ├── ops/
│   ├── repositories/
│   ├── services/
│   └── ui/
├── mcp_server/                    # NEW: MCP server for Claude Code
│   ├── __init__.py
│   ├── server.py                  # stdio MCP server
│   └── tools.py                   # MCP tool definitions wrapping InspectService
├── skills/                        # NEW: User-invocable skills
│   ├── egtsr-setup.md
│   ├── egtsr-status.md
│   ├── egtsr-inspect.md
│   └── egtsr-doctor.md
├── pyproject.toml                 # Package config (existing, extended)
└── docs/
    └── CLAUDE_CODE_PLUGIN_PLAN.md # This file
```

---

## Phase A: MCP Server Implementation

### Objective
Wrap existing `InspectService` and `HealthChecker` as MCP tools that Claude can call.

### MCP Tools

| Tool Name | Input | Output | Source |
|-----------|-------|--------|--------|
| `egtsr_inspect_obligations` | `session_id: str` | Open obligations with counts | `InspectService.inspect_obligations()` |
| `egtsr_inspect_stale` | `session_id: str` | Stale/live ticket breakdown | `InspectService.inspect_stale()` |
| `egtsr_inspect_capsule` | `session_id: str` | Latest capsule + audit report | `InspectService.inspect_capsule()` |
| `egtsr_resume_status` | `session_id: str` | Resume gate state | `InspectService.resume_status()` |
| `egtsr_doctor` | `project_dir: str` | Health check results | `HealthChecker.check()` |
| `egtsr_session_summary` | `session_id: str` | Combined session overview | New: aggregates all inspect results |

### MCP Server (stdio transport)

```python
# mcp_server/server.py
# Uses MCP SDK (mcp python package) with stdio transport
# Claude Code spawns this process and communicates via stdin/stdout

class EGTSRMCPServer:
    def __init__(self):
        self.server = Server("egtsr")
        self._register_tools()

    def _register_tools(self):
        @self.server.tool()
        async def egtsr_inspect_obligations(session_id: str) -> str:
            """Inspect open obligations for a session."""
            ...

        @self.server.tool()
        async def egtsr_inspect_stale(session_id: str) -> str:
            """Inspect stale invalidation tickets."""
            ...

        @self.server.tool()
        async def egtsr_inspect_capsule(session_id: str) -> str:
            """Inspect latest decision capsule and audit report."""
            ...

        @self.server.tool()
        async def egtsr_resume_status(session_id: str) -> str:
            """Check resume gate status and blocking conditions."""
            ...

        @self.server.tool()
        async def egtsr_doctor(project_dir: str = ".") -> str:
            """Run health diagnosis on EGTSR runtime."""
            ...
```

### Dependencies
- `mcp` Python package (MCP SDK)
- Existing `egtsr_runtime` (no changes to core)

### Files to Create
- `mcp_server/__init__.py`
- `mcp_server/server.py`
- `mcp_server/tools.py`

### Tests
- MCP tool call → valid JSON response
- All tools are read-only (no DB mutation)
- Server starts and responds to tool list request

---

## Phase B: Plugin Manifest + Skills

### plugin.json

```json
{
  "name": "egtsr",
  "displayName": "EGTSR Runtime",
  "version": "0.1.0",
  "description": "Execution-Grounded Task-State Runtime — obligation tracking, stale quarantine, resume safety for Claude Code",
  "author": "argoss",
  "license": "MIT",
  "mcp": {
    "command": "python3",
    "args": ["-m", "mcp_server.server"],
    "transport": "stdio"
  },
  "hooks": {
    "SessionStart": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 -m egtsr_runtime.hooks.entrypoint session_start"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 -m egtsr_runtime.hooks.entrypoint user_prompt_submit"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 -m egtsr_runtime.hooks.entrypoint post_tool_use"
          }
        ]
      }
    ],
    "SessionEnd": [
      {
        "matcher": "",
        "hooks": [
          {
            "type": "command",
            "command": "python3 -m egtsr_runtime.hooks.entrypoint session_end"
          }
        ]
      }
    ]
  },
  "skills": [
    "skills/egtsr-setup.md",
    "skills/egtsr-status.md",
    "skills/egtsr-inspect.md",
    "skills/egtsr-doctor.md"
  ]
}
```

### Skills

#### /egtsr-setup
Activate EGTSR in current project. Creates `.egtsr/` directory, initializes DB, verifies hooks.

#### /egtsr-status
Quick session status: open obligations count, stale count, resume gate, last capsule audit.

#### /egtsr-inspect
Detailed inspection: obligations, stale queue, capsule content, verify results, attempt families.

#### /egtsr-doctor
Runtime health check: DB integrity, artifact existence, hook config, metrics anomalies.

### Files to Create
- `.claude-plugin/plugin.json`
- `skills/egtsr-setup.md`
- `skills/egtsr-status.md`
- `skills/egtsr-inspect.md`
- `skills/egtsr-doctor.md`

---

## Phase C: Hooks Integration into Plugin Manifest

### Objective
Move hook registration from `egtsr setup` CLI into plugin.json so hooks auto-register on plugin install.

### Changes
- plugin.json `hooks` section replaces manual `.claude/settings.local.json` setup
- `egtsr setup` CLI becomes optional (for non-plugin installs)
- Hook commands remain the same (`python3 -m egtsr_runtime.hooks.entrypoint <hook>`)

### Backward Compatibility
- pip install + `egtsr setup` still works for users who don't use plugin system
- Plugin install is the recommended path

---

## Phase D: Testing

### MCP Server Tests
- Tool discovery: server lists all 6 tools
- Tool execution: each tool returns valid JSON for valid session_id
- Error handling: invalid session_id returns error message (not crash)
- Read-only: DB state unchanged after tool calls
- Server lifecycle: start, serve, shutdown cleanly

### Skill Tests
- Each skill file is valid markdown with proper frontmatter
- Skill invocation triggers correct MCP tool calls

### Integration Tests
- Full flow: plugin install → SessionStart hook → UserPromptSubmit hook → Claude calls inspect tool → returns state
- Resume scenario: resume → edit blocked → Claude calls resume_status → sees block reason

### Existing Tests
- All 145 existing tests must continue to pass

---

## Phase E: Distribution

### GitHub Repository
- Clean up repo for public release
- Add README with installation instructions
- Add LICENSE (MIT)
- Add CHANGELOG.md

### Plugin Marketplace
```bash
# User installs from marketplace
claude plugin add egtsr

# Or from GitHub
claude plugin add argoss/egtsr
```

### PyPI (optional, for pip users)
```bash
pip install egtsr-runtime
egtsr setup  # manual hook registration
```

---

## Implementation Order

| Step | Phase | Effort | Dependencies |
|------|-------|--------|-------------|
| 1 | **A: MCP Server** | Medium | `mcp` Python package |
| 2 | **B: plugin.json + skills** | Low | Phase A |
| 3 | **C: Hooks integration** | Low | Phase B |
| 4 | **D: Testing** | Medium | Phase A, B, C |
| 5 | **E: Distribution** | Low | Phase D |

### Estimated Scope
- New files: ~10
- Modified files: ~3 (pyproject.toml, existing exports)
- New dependency: `mcp` Python SDK
- Total new code: ~500-800 lines

---

## Architecture After Plugin

```
Claude Code Session
│
├─ Hooks (background, every event)
│  ├─ SessionStart     → bootstrap session, evaluate resume gate
│  ├─ UserPromptSubmit → compile capsule, audit, gate decision
│  ├─ PostToolUse      → ingest evidence, invalidate stale
│  └─ SessionEnd       → save snapshot, artifacts
│
├─ MCP Tools (Claude calls directly)
│  ├─ egtsr_inspect_obligations  → "3 open, 1 reopened"
│  ├─ egtsr_inspect_stale        → "2 live tickets blocking"
│  ├─ egtsr_inspect_capsule      → "last audit: PASS, 217 tokens"
│  ├─ egtsr_resume_status        → "edit_blocked: true, reason: stale"
│  ├─ egtsr_doctor               → "DB ok, 1 missing artifact"
│  └─ egtsr_session_summary      → aggregated overview
│
└─ Skills (user invokes)
   ├─ /egtsr-setup    → activate in project
   ├─ /egtsr-status   → quick status
   ├─ /egtsr-inspect  → detailed view
   └─ /egtsr-doctor   → health check
```

### Data Flow

```
User prompt → Hook (UserPromptSubmit)
                ├─ compile decision capsule
                ├─ audit (omission/stale/unsupported)
                ├─ gate decision (allow/block)
                └─ store capsule + event in DB
                        │
Claude (during response) │
  ├─ calls MCP tool ─────┘
  │   egtsr_inspect_obligations("session-123")
  │   → returns structured obligation state
  │
  └─ uses state in reasoning
      "There are 2 open obligations. One has stale evidence.
       I should re-read the file before editing."
```

---

## Risk and Mitigation

| Risk | Mitigation |
|------|-----------|
| MCP SDK not stable | Pin version, minimal API surface |
| Plugin format changes | Abstract plugin.json generation |
| Hook + MCP race condition | Hooks write DB first, MCP reads after |
| Performance (MCP server startup) | Keep server lightweight, lazy imports |
| Claude over-relying on EGTSR state | Skills prompt Claude to verify, not blindly trust |

---

## Success Criteria

- [ ] `claude plugin add egtsr` installs cleanly
- [ ] Hooks auto-register without manual setup
- [ ] Claude can call `egtsr_inspect_obligations` and get valid response
- [ ] `/egtsr-status` shows session summary
- [ ] All 145+ existing tests pass
- [ ] MCP server starts in < 500ms
- [ ] No new external dependencies except `mcp` SDK

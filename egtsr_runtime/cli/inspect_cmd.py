"""CLI wrapper for MCP inspect commands."""
from __future__ import annotations

import json
from pathlib import Path

from egtsr_runtime.db.runtime import SqliteRuntime
from egtsr_runtime.db.uow import SqliteUnitOfWork
from egtsr_runtime.mcp.inspect import InspectService
from egtsr_runtime.runtime_locator import resolve_project_dir


def run_inspect(target: str, session_id: str, project_dir: str = ".") -> None:
    """Run inspect command and pretty-print JSON result."""
    from egtsr_runtime.constants import DB_FILENAME

    db_path = resolve_project_dir(project_dir) / DB_FILENAME
    if not db_path.exists():
        raise SystemExit(f"EGTSR DB not found: {db_path}")

    runtime = SqliteRuntime(str(db_path))
    conn = runtime.boot()
    try:
        with SqliteUnitOfWork(conn) as uow:
            service = InspectService(uow)
            handlers = {
                "obligations": service.inspect_obligations,
                "stale": service.inspect_stale,
                "capsule": service.inspect_capsule,
                "resume": service.resume_status,
            }
            result = handlers[target](session_id)
    finally:
        runtime.shutdown()

    print(json.dumps(result, indent=2, ensure_ascii=False))

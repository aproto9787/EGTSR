from __future__ import annotations

from egtsr_runtime.db.runtime import SqliteRuntime
from egtsr_runtime.db.uow import SqliteUnitOfWork
from egtsr_runtime.mcp.inspect import InspectService

_KNOWN_TOOLS = {"inspect_obligations", "inspect_stale", "inspect_capsule", "resume_status"}


def handle_mcp_tool(tool_name: str, args: dict, db_path: str) -> dict:
    """Dispatch MCP tool calls. All read-only."""
    if tool_name not in _KNOWN_TOOLS:
        return {"error": f"Unknown tool: {tool_name}"}

    runtime = SqliteRuntime(db_path)
    conn = runtime.boot()
    try:
        with SqliteUnitOfWork(conn) as uow:
            service = InspectService(uow)
            if tool_name == "inspect_obligations":
                return service.inspect_obligations(args["session_id"])
            elif tool_name == "inspect_stale":
                return service.inspect_stale(args["session_id"])
            elif tool_name == "inspect_capsule":
                return service.inspect_capsule(args["session_id"])
            elif tool_name == "resume_status":
                return service.resume_status(args["session_id"])
    finally:
        runtime.shutdown()

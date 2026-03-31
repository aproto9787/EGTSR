from __future__ import annotations

import subprocess
from dataclasses import dataclass


@dataclass(slots=True)
class RepoInspectResult:
    head_hash: str | None
    dirty: bool
    branch: str | None



def inspect_repo(cwd: str) -> RepoInspectResult:
    """Inspect git repo state at cwd."""
    try:
        head_hash = _run_git(cwd, "rev-parse", "HEAD")
        status_output = _run_git(cwd, "status", "--porcelain")
        branch = _run_git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    except Exception:
        return RepoInspectResult(head_hash=None, dirty=False, branch=None)

    if head_hash is None or branch is None or status_output is None:
        return RepoInspectResult(head_hash=None, dirty=False, branch=None)

    return RepoInspectResult(
        head_hash=head_hash,
        dirty=bool(status_output.strip()),
        branch=branch,
    )



def _run_git(cwd: str, *args: str) -> str | None:
    completed = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()

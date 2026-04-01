"""Project shard path resolution for global runtime home."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from egtsr_runtime.constants import (
    DAEMON_DIR,
    DB_FILENAME,
    DEBUG_DIR,
    EXPORTS_DIR,
    LAST_GOOD_CAPSULE,
    LOG_FILENAME,
    MANIFEST_FILENAME,
    RAW_EVENTS_DIR,
    REPORTS_DIR,
    RESUME_GATE,
)
from egtsr_runtime.runtime_home import resolve_egtsr_home


def canonicalize_repo_root(repo_root: str | Path) -> str:
    """Normalize path: resolve symlinks, make absolute."""
    return str(Path(repo_root).expanduser().resolve())


def compute_repo_hash(repo_root: str | Path) -> str:
    """sha256(canonical_repo_root)[:16] — 16-char hex prefix."""
    canonical = canonicalize_repo_root(repo_root)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def resolve_project_dir(repo_root: str | Path) -> Path:
    """Return the project shard directory under EGTSR_HOME.

    Does NOT create the project shard — use
    ``resolve_project_runtime_paths`` when directories must exist.
    """
    egtsr_home = resolve_egtsr_home()
    repo_hash = compute_repo_hash(repo_root)
    return egtsr_home / "projects" / repo_hash


def resolve_project_runtime_paths(repo_root: str | Path):
    """Resolve all runtime paths for a project and ensure directories exist.

    Returns a ``RuntimePaths`` instance.
    """
    from egtsr_runtime.paths import RuntimePaths

    canonical_root = canonicalize_repo_root(repo_root)
    egtsr_home = resolve_egtsr_home()
    repo_hash = compute_repo_hash(repo_root)
    project_dir = egtsr_home / "projects" / repo_hash

    raw_events_dir = project_dir / RAW_EVENTS_DIR
    debug_dir = project_dir / DEBUG_DIR
    reports_dir = project_dir / REPORTS_DIR
    daemon_dir = project_dir / DAEMON_DIR
    exports_dir = project_dir / EXPORTS_DIR

    for d in (project_dir, raw_events_dir, debug_dir, reports_dir, daemon_dir, exports_dir):
        d.mkdir(parents=True, exist_ok=True)

    update_manifest(egtsr_home, canonical_root, repo_hash)

    return RuntimePaths(
        repo_root=canonical_root,
        egtsr_dir=str(project_dir),
        db_path=str(project_dir / DB_FILENAME),
        log_path=str(project_dir / LOG_FILENAME),
        last_good_capsule_path=str(project_dir / LAST_GOOD_CAPSULE),
        resume_gate_path=str(project_dir / RESUME_GATE),
        raw_events_dir=str(raw_events_dir),
        debug_dir=str(debug_dir),
        reports_dir=str(reports_dir),
        daemon_dir=str(daemon_dir),
        exports_dir=str(exports_dir),
    )


def read_manifest(egtsr_home: Path) -> dict:
    """Read manifest.json mapping repo_hash to repo_root."""
    manifest_path = egtsr_home / MANIFEST_FILENAME
    if not manifest_path.is_file():
        return {}
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def update_manifest(egtsr_home: Path, repo_root: str, repo_hash: str) -> None:
    """Add or update repo_hash ↔ repo_root mapping in manifest.json."""
    manifest_path = egtsr_home / MANIFEST_FILENAME
    data = read_manifest(egtsr_home)

    projects = data.get("projects", {})
    existing = projects.get(repo_hash, {})
    if existing.get("repo_root") == repo_root:
        return  # Already up-to-date

    projects[repo_hash] = {
        "repo_root": repo_root,
        "display_name": Path(repo_root).name,
    }
    data["projects"] = projects

    tmp = manifest_path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    tmp.replace(manifest_path)

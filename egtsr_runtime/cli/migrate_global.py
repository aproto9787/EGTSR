"""Migrate legacy .egtsr/ to global EGTSR_HOME shard."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

from egtsr_runtime.constants import EGTSR_DIR_NAME


def migrate_to_global(project_dir: str = ".") -> int:
    """Migrate a project's legacy .egtsr/ directory to the global runtime home.

    Steps:
    1. Verify project_dir/.egtsr/ exists
    2. Compute repo_hash for this project
    3. Create EGTSR_HOME/projects/<hash>/
    4. Copy session.db, raw_events/, reports/, debug/, daemon/ to shard
    5. Update manifest.json
    6. Write tombstone to .egtsr/ marking migration complete
    """
    project_path = Path(project_dir).expanduser().resolve()
    legacy_dir = project_path / EGTSR_DIR_NAME

    if not legacy_dir.is_dir():
        print(f"No legacy .egtsr/ directory found at {legacy_dir}", file=sys.stderr)
        return 1

    # Check for existing tombstone
    tombstone_path = legacy_dir / ".migrated"
    if tombstone_path.is_file():
        try:
            tombstone = json.loads(tombstone_path.read_text(encoding="utf-8"))
            print(
                f"Already migrated (repo_hash: {tombstone.get('repo_hash')}, "
                f"runtime_home: {tombstone.get('runtime_home')})",
                file=sys.stderr,
            )
        except (json.JSONDecodeError, OSError):
            print("Already migrated (tombstone present)", file=sys.stderr)
        return 0

    from egtsr_runtime.runtime_home import resolve_egtsr_home
    from egtsr_runtime.runtime_locator import (
        canonicalize_repo_root,
        compute_repo_hash,
        update_manifest,
    )

    canonical_root = canonicalize_repo_root(project_path)
    repo_hash = compute_repo_hash(project_path)
    egtsr_home = resolve_egtsr_home()
    shard_dir = egtsr_home / "projects" / repo_hash

    if shard_dir.exists() and any(shard_dir.iterdir()):
        print(
            f"Target shard already exists and is non-empty: {shard_dir}",
            file=sys.stderr,
        )
        print("Aborting to avoid data loss. Remove it manually to retry.", file=sys.stderr)
        return 1

    shard_dir.mkdir(parents=True, exist_ok=True)

    # Copy contents
    copied: list[str] = []
    for item in legacy_dir.iterdir():
        if item.name == ".migrated":
            continue
        dest = shard_dir / item.name
        if item.is_dir():
            shutil.copytree(item, dest, dirs_exist_ok=True)
        else:
            shutil.copy2(item, dest)
        copied.append(item.name)

    # Update manifest
    update_manifest(egtsr_home, canonical_root, repo_hash)

    # Write tombstone
    tombstone_data = {
        "migrated": True,
        "repo_hash": repo_hash,
        "runtime_home": str(egtsr_home),
        "shard_dir": str(shard_dir),
    }
    tombstone_path.write_text(
        json.dumps(tombstone_data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print(f"Migration complete: {legacy_dir} -> {shard_dir}")
    print(f"  repo_hash: {repo_hash}")
    print(f"  copied: {', '.join(sorted(copied))}")
    print(f"  tombstone: {tombstone_path}")
    print(
        "\nThe legacy .egtsr/ directory is preserved with a tombstone marker. "
        "You may remove it manually after verifying the migration."
    )
    return 0

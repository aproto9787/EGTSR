"""Shared path normalization for EGTSR.

All writers and readers MUST use ``normalize_path`` so that
path_subject_index lookups are consistent.
"""
from __future__ import annotations

import os


def normalize_path(path: str | None, repo_root: str | None = None) -> str:
    """Normalize a file path for index storage/lookup.

    Rules (from 04_State_Storage_Projection_and_Migration §6):
    - str(path).strip()
    - empty -> return ""
    - os.path.normpath
    - if repo_root is given and path is absolute under repo_root -> relative
    """
    if path is None:
        return ""
    cleaned = str(path).strip()
    if not cleaned:
        return ""
    normed = os.path.normpath(cleaned)
    if repo_root and os.path.isabs(normed):
        normed_root = os.path.normpath(repo_root)
        # Use commonpath to check if normed is under normed_root
        try:
            rel = os.path.relpath(normed, normed_root)
        except ValueError:
            # Different drives on Windows
            return normed
        if not rel.startswith(".."):
            return rel
    return normed

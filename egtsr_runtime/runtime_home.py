"""EGTSR_HOME resolver — global runtime data directory."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def resolve_egtsr_home() -> Path:
    """Resolve EGTSR global home directory.

    Priority:
    1. EGTSR_HOME env var (explicit user override)
    2. CLAUDE_PLUGIN_DATA env var (marketplace mode)
    3. ~/.local/share/egtsr (Linux/Mac) or %LOCALAPPDATA%\\EGTSR (Windows)
    """
    env_home = os.environ.get("EGTSR_HOME")
    if env_home:
        p = Path(env_home).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    plugin_data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if plugin_data:
        p = Path(plugin_data).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    if sys.platform == "win32":
        local_app = os.environ.get("LOCALAPPDATA")
        if local_app:
            p = Path(local_app) / "EGTSR"
        else:
            p = Path.home() / "AppData" / "Local" / "EGTSR"
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        if xdg:
            p = Path(xdg) / "egtsr"
        else:
            p = Path.home() / ".local" / "share" / "egtsr"

    p = p.resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def is_marketplace_mode() -> bool:
    """True when CLAUDE_PLUGIN_DATA is set (marketplace install)."""
    return bool(os.environ.get("CLAUDE_PLUGIN_DATA"))

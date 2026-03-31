"""Mode matrix — map runtime_mode to individual feature flags.

Modes:
- ``legacy``:  All flags off.  Current default.
- ``daemon``:  daemon + incremental + projection + reverse-index all on.
- ``shadow``:  Same flags as daemon, but dual-run with legacy diff.

Individual flag overrides (env / runtime_flags.json) always take precedence
over the mode matrix defaults, so operators can mix and match.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from egtsr_runtime.config import RuntimeConfig

# Flags set by each mode.  True means "on by default for this mode".
_MODE_DEFAULTS: dict[str, dict[str, bool]] = {
    "legacy": {
        "enable_daemon": False,
        "enable_incremental_compile": False,
        "enable_projection_tables": False,
        "enable_reverse_index": False,
    },
    "daemon": {
        "enable_daemon": True,
        "enable_incremental_compile": True,
        "enable_projection_tables": True,
        "enable_reverse_index": True,
    },
    "shadow": {
        "enable_daemon": True,
        "enable_incremental_compile": True,
        "enable_projection_tables": True,
        "enable_reverse_index": True,
    },
}


def apply_mode_matrix(config: RuntimeConfig) -> RuntimeConfig:
    """Set feature flags from ``config.runtime_mode`` as baseline defaults.

    Only writes a flag when the flag is still at its code-level default
    (``False``).  If a flag was already set via env / runtime_flags.json
    (i.e. ``apply_overrides`` already ran), it is left untouched.
    """
    mode_flags = _MODE_DEFAULTS.get(config.runtime_mode)
    if mode_flags is None:
        return config

    for flag_name, mode_value in mode_flags.items():
        current = getattr(config, flag_name, None)
        # Only apply if the flag is still at code default (False).
        # If it was explicitly set via env/file override, leave it.
        if current is False and mode_value is True:
            setattr(config, flag_name, True)

    return config

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Literal

RuntimeMode = Literal["legacy", "daemon", "shadow"]

# Feature flags that control improvement paths (all default-off)
_FEATURE_FLAGS = (
    "enable_daemon",
    "enable_incremental_compile",
    "enable_projection_tables",
    "enable_reverse_index",
)

_ENV_PREFIX = "EGTSR_"


@dataclass(slots=True)
class RuntimeConfig:
    repo_root: str
    egtsr_dir: str
    db_path: str
    enable_compact_hooks: bool = False
    max_decision_tokens: int = 900

    # --- Step 00: runtime mode + feature flags ---
    runtime_mode: RuntimeMode = "legacy"
    enable_daemon: bool = False
    enable_incremental_compile: bool = False
    enable_projection_tables: bool = False
    enable_reverse_index: bool = False


def load_runtime_flags(egtsr_dir: str) -> dict[str, object]:
    """Load runtime flags from .egtsr/runtime_flags.json.

    Returns an empty dict when the file is absent or unparseable.
    """
    flags_path = Path(egtsr_dir) / "runtime_flags.json"
    if not flags_path.is_file():
        return {}
    try:
        with flags_path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def _env_override(name: str) -> str | None:
    """Return env var value for EGTSR_{NAME} or None."""
    return os.environ.get(f"{_ENV_PREFIX}{name.upper()}")


def _coerce_bool(value: str) -> bool:
    return value.lower() in ("1", "true", "yes", "on")


def apply_overrides(config: RuntimeConfig) -> RuntimeConfig:
    """Apply env var and runtime_flags.json overrides to *config* in-place.

    Priority: env var > runtime_flags.json > mode matrix > code default.

    The mode matrix (Step 07) sets baseline flag defaults from
    ``runtime_mode``.  Explicit env/file overrides always win.
    """
    file_flags = load_runtime_flags(config.egtsr_dir)

    # runtime_mode
    file_mode = file_flags.get("runtime_mode")
    if isinstance(file_mode, str) and file_mode in ("legacy", "daemon", "shadow"):
        config.runtime_mode = file_mode  # type: ignore[assignment]
    env_mode = _env_override("runtime_mode")
    if env_mode is not None and env_mode in ("legacy", "daemon", "shadow"):
        config.runtime_mode = env_mode  # type: ignore[assignment]

    # Step 07: apply mode matrix defaults before explicit overrides
    from egtsr_runtime.compat.mode_matrix import apply_mode_matrix

    apply_mode_matrix(config)

    # boolean feature flags (explicit overrides win over mode matrix)
    for flag_name in _FEATURE_FLAGS:
        # file override
        file_val = file_flags.get(flag_name)
        if isinstance(file_val, bool):
            setattr(config, flag_name, file_val)
        elif isinstance(file_val, str):
            setattr(config, flag_name, _coerce_bool(file_val))

        # env override (takes precedence)
        env_val = _env_override(flag_name)
        if env_val is not None:
            setattr(config, flag_name, _coerce_bool(env_val))

    return config


def is_shadow_mode(config: RuntimeConfig) -> bool:
    """Return True when dual-run shadow comparison is active."""
    return config.runtime_mode == "shadow"

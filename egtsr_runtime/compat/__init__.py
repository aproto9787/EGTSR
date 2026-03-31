"""Compatibility Adapter + Dual-Run Cutover (Step 07) and Release Cutover (Step 09).

This package preserves external contracts (hook stdout JSON, CLI, MCP,
snapshot file formats) while allowing internal runtime paths to switch
between legacy and improved implementations.
"""
from egtsr_runtime.compat.cutover import CutoverManager, CutoverState
from egtsr_runtime.compat.mode_matrix import apply_mode_matrix
from egtsr_runtime.compat.release_check import ReleaseChecker, ReleaseCheckReport
from egtsr_runtime.compat.shadow_runner import (
    ShadowCompileResult,
    ShadowCompileRunner,
    ShadowInvalidationResult,
    ShadowInvalidationRunner,
)

__all__ = [
    "apply_mode_matrix",
    "CutoverManager",
    "CutoverState",
    "ReleaseChecker",
    "ReleaseCheckReport",
    "ShadowCompileResult",
    "ShadowCompileRunner",
    "ShadowInvalidationResult",
    "ShadowInvalidationRunner",
]

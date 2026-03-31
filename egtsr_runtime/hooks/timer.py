"""Common timer wrapper for hook handlers.

Records hook_name, start_time, end_time, duration_ms for each hook invocation.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, TypeVar

T = TypeVar("T")


@dataclass(slots=True)
class HookTiming:
    hook_name: str
    start_time: float
    end_time: float
    duration_ms: float


# Module-level accumulator for the current process lifetime.
_timings: list[HookTiming] = []


def timed_hook(hook_name: str, fn: Callable[[], T]) -> tuple[T, HookTiming]:
    """Run *fn* and return ``(result, timing)``."""
    start = time.perf_counter()
    result = fn()
    end = time.perf_counter()
    timing = HookTiming(
        hook_name=hook_name,
        start_time=start,
        end_time=end,
        duration_ms=(end - start) * 1000.0,
    )
    _timings.append(timing)
    return result, timing


def get_timings() -> list[HookTiming]:
    """Return a copy of all recorded timings."""
    return list(_timings)


def clear_timings() -> None:
    """Reset the accumulated timings."""
    _timings.clear()

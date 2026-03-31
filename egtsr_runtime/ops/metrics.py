"""Metrics collection — counters, timings, percentiles, structured recording.

Step 08 extends the original counter-only MetricsEmitter with:
- timing sample recording and percentile calculation
- MetricsWriter for structured JSON-line event logging
- MetricsReader for querying recorded metrics
"""
from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path


def _percentile(sorted_data: list[float], p: float) -> float:
    """Calculate p-th percentile (0-100) from pre-sorted data."""
    if not sorted_data:
        return 0.0
    n = len(sorted_data)
    if n == 1:
        return sorted_data[0]
    k = (n - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, n - 1)
    d = k - f
    return sorted_data[f] + d * (sorted_data[c] - sorted_data[f])


class MetricsEmitter:
    def __init__(self):
        self._counters: dict[str, int] = {}
        self._timings: dict[str, list[float]] = {}

    def incr(self, name: str, value: int = 1) -> None:
        self._counters[name] = self._counters.get(name, 0) + value

    def get(self, name: str) -> int:
        return self._counters.get(name, 0)

    def record_timing(self, name: str, duration_ms: float) -> None:
        """Record a timing sample in milliseconds."""
        if name not in self._timings:
            self._timings[name] = []
        self._timings[name].append(duration_ms)

    def get_timings(self, name: str) -> list[float]:
        """Return a copy of recorded timing samples."""
        return list(self._timings.get(name, []))

    def percentile(self, name: str, p: float) -> float:
        """Return the p-th percentile (0-100) for a timing metric."""
        data = self._timings.get(name, [])
        if not data:
            return 0.0
        return _percentile(sorted(data), p)

    def timing_summary(self, name: str) -> dict:
        """Return {count, min, max, mean, p50, p95, p99} for a timing metric."""
        data = self._timings.get(name, [])
        if not data:
            return {"count": 0, "min": 0.0, "max": 0.0, "mean": 0.0,
                    "p50": 0.0, "p95": 0.0, "p99": 0.0}
        s = sorted(data)
        return {
            "count": len(data),
            "min": round(s[0], 3),
            "max": round(s[-1], 3),
            "mean": round(statistics.mean(data), 3),
            "p50": round(_percentile(s, 50), 3),
            "p95": round(_percentile(s, 95), 3),
            "p99": round(_percentile(s, 99), 3),
        }

    def export_json(self) -> dict:
        result = dict(self._counters)
        for name in self._timings:
            result[f"{name}.summary"] = self.timing_summary(name)
        return result

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(self.export_json(), f, indent=2)


# Standard counter names
COUNTER_SESSION_START = "hook_session_start_total"
COUNTER_PROMPT_SUBMIT = "hook_prompt_submit_total"
COUNTER_POST_TOOL_USE = "hook_post_tool_use_total"
COUNTER_FAIL_OPEN = "hook_fail_open_total"
COUNTER_AUDIT_FAIL = "compile_audit_fail_total"
COUNTER_EDIT_BLOCKED = "resume_edit_block_total"
COUNTER_STALE_TICKET = "stale_ticket_total"
COUNTER_OBLIGATION_REOPENED = "obligation_reopened_total"
COUNTER_VERIFY_FAIL = "verify_fail_total"
COUNTER_ATTEMPT_FAMILY = "attempt_family_created_total"

# Timing metric names (Step 08)
TIMING_HOOK_SESSION_START = "hook.session_start.ms"
TIMING_HOOK_USER_PROMPT_SUBMIT = "hook.user_prompt_submit.ms"
TIMING_HOOK_POST_TOOL_USE = "hook.post_tool_use.ms"
TIMING_HOOK_SESSION_END = "hook.session_end.ms"
TIMING_COMPILER_RENDER = "compiler.render.ms"
TIMING_COMPILER_AUDIT = "compiler.audit.ms"
TIMING_INVALIDATION_APPLY = "invalidation.apply.ms"
TIMING_INVALIDATION_REVERSE_LOOKUP = "invalidation.reverse_lookup.ms"
TIMING_DB_TRANSACTION = "db.transaction.ms"

# Fallback counter names (Step 08)
COUNTER_COMPILER_FULL_FALLBACK = "compiler.full_fallback.total"
COUNTER_COMPILER_INCREMENTAL = "compiler.incremental.total"
COUNTER_DAEMON_FALLBACK = "daemon.fallback.total"
COUNTER_DAEMON_RESTART = "daemon.restart.total"


class MetricsWriter:
    """Append structured JSON-line metric events to .egtsr/metrics/."""

    def __init__(self, metrics_dir: str) -> None:
        self._dir = Path(metrics_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self._path = self._dir / "metrics.jsonl"

    def write_event(self, event_type: str, data: dict,
                    session_id: str | None = None) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            "session_id": session_id,
            **data,
        }
        with self._path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def write_hook_timing(self, hook_name: str, duration_ms: float,
                          session_id: str | None = None, **extra) -> None:
        self.write_event(
            f"hook.{hook_name}.timing",
            {"hook_name": hook_name, "duration_ms": round(duration_ms, 3), **extra},
            session_id=session_id,
        )

    def write_compile_timing(self, duration_ms: float, mode: str = "legacy",
                             session_id: str | None = None, **extra) -> None:
        self.write_event(
            "compiler.render.timing",
            {"duration_ms": round(duration_ms, 3), "mode": mode, **extra},
            session_id=session_id,
        )

    def write_invalidation_timing(self, duration_ms: float,
                                  changed_count: int = 0,
                                  impacted_count: int = 0,
                                  session_id: str | None = None) -> None:
        self.write_event(
            "invalidation.apply.timing",
            {"duration_ms": round(duration_ms, 3),
             "changed_count": changed_count,
             "impacted_count": impacted_count},
            session_id=session_id,
        )

    def write_fallback(self, component: str, reason: str,
                       session_id: str | None = None) -> None:
        self.write_event(
            f"{component}.fallback",
            {"component": component, "reason": reason},
            session_id=session_id,
        )


class MetricsReader:
    """Read and query structured metrics from metrics.jsonl."""

    def __init__(self, metrics_dir: str) -> None:
        self._path = Path(metrics_dir) / "metrics.jsonl"

    def read_all(self) -> list[dict]:
        if not self._path.is_file():
            return []
        events: list[dict] = []
        with self._path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
        return events

    def query(self, event_type: str | None = None,
              session_id: str | None = None) -> list[dict]:
        events = self.read_all()
        if event_type:
            events = [e for e in events if e.get("event") == event_type]
        if session_id:
            events = [e for e in events if e.get("session_id") == session_id]
        return events

    def hook_timing_summary(self) -> dict[str, dict]:
        """Aggregate hook timings into {hook_name: {count, min, max, mean, p50, p95, p99}}."""
        timings: dict[str, list[float]] = {}
        for event in self.read_all():
            if event.get("event", "").endswith(".timing") and "hook_name" in event:
                hook = event["hook_name"]
                ms = event.get("duration_ms", 0.0)
                timings.setdefault(hook, []).append(ms)

        summaries: dict[str, dict] = {}
        for hook, data in timings.items():
            s = sorted(data)
            summaries[hook] = {
                "count": len(data),
                "min": round(s[0], 3),
                "max": round(s[-1], 3),
                "mean": round(sum(data) / len(data), 3),
                "p50": round(_percentile(s, 50), 3),
                "p95": round(_percentile(s, 95), 3),
                "p99": round(_percentile(s, 99), 3),
            }
        return summaries

    def fallback_summary(self) -> dict[str, dict[str, int]]:
        """Aggregate fallback events by component → reason → count."""
        by_component: dict[str, dict[str, int]] = {}
        for event in self.read_all():
            if event.get("event", "").endswith(".fallback"):
                component = event.get("component", "unknown")
                reason = event.get("reason", "unknown")
                by_component.setdefault(component, {})
                by_component[component][reason] = by_component[component].get(reason, 0) + 1
        return by_component

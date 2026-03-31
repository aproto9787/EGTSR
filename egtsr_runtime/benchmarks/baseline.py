"""Baseline report generation and persistence.

Produces `.egtsr/reports/baseline_{timestamp}.json` with latency,
scale, and token metrics captured from the legacy path.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass(slots=True)
class HookLatencyEntry:
    hook_name: str
    duration_ms: float


@dataclass(slots=True)
class BaselineReport:
    timestamp: str
    runtime_mode: str = "legacy"
    hook_latencies: list[HookLatencyEntry] = field(default_factory=list)
    session_size: int = 0
    obligation_count: int = 0
    evidence_count: int = 0
    assertion_count: int = 0
    compile_duration_ms: float = 0.0
    token_estimate: int = 0
    scenario_results: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "runtime_mode": self.runtime_mode,
            "hook_latencies": [asdict(entry) for entry in self.hook_latencies],
            "session_size": self.session_size,
            "obligation_count": self.obligation_count,
            "evidence_count": self.evidence_count,
            "assertion_count": self.assertion_count,
            "compile_duration_ms": round(self.compile_duration_ms, 3),
            "token_estimate": self.token_estimate,
            "scenario_results": self.scenario_results,
        }


def save_baseline_report(report: BaselineReport, reports_dir: str) -> str:
    """Write baseline report JSON and return the file path."""
    dir_path = Path(reports_dir)
    dir_path.mkdir(parents=True, exist_ok=True)
    ts = report.timestamp.replace(":", "-").replace(".", "-")
    filename = f"baseline_{ts}.json"
    out_path = dir_path / filename
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(report.to_dict(), fh, indent=2, ensure_ascii=False)
    return str(out_path)


def make_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

"""Regression gate — compares benchmark results against baseline thresholds.

Provides PASS/FAIL verdict with per-check detail for CI integration.
Exit code: 0 = PASS, 1 = FAIL.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from egtsr_runtime.benchmarks.baseline import BaselineReport, HookLatencyEntry, make_timestamp
from egtsr_runtime.ops.metrics import _percentile


@dataclass(slots=True)
class GateThresholds:
    """Configurable thresholds for regression gate checks."""
    latency_p95_max_ms: float = 200.0
    latency_p95_regression_pct: float = 0.10  # max 10% worse than baseline
    scale_slope_max: float = 5.0  # max compile ms per additional obligation
    shadow_critical_diff_max: int = 0
    fallback_rate_max: float = 0.05  # max 5% fallback rate


@dataclass(slots=True)
class GateCheck:
    """Single gate check result."""
    name: str
    passed: bool
    actual: float | int
    threshold: float | int
    message: str


@dataclass(slots=True)
class RegressionGateReport:
    """Full regression gate evaluation report."""
    timestamp: str
    overall_pass: bool
    checks: list[GateCheck] = field(default_factory=list)
    baseline_path: str | None = None

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "overall_pass": self.overall_pass,
            "baseline_path": self.baseline_path,
            "checks": [
                {
                    "name": c.name,
                    "passed": c.passed,
                    "actual": c.actual,
                    "threshold": c.threshold,
                    "message": c.message,
                }
                for c in self.checks
            ],
        }


def _linear_slope(xs: list[float | int], ys: list[float]) -> float:
    """Simple linear regression slope (least squares)."""
    n = len(xs)
    if n < 2:
        return 0.0
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    numerator = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    denominator = sum((x - x_mean) ** 2 for x in xs)
    if denominator == 0:
        return 0.0
    return numerator / denominator


class RegressionGate:
    """Evaluate benchmark results against baseline with configurable thresholds."""

    def __init__(self, thresholds: GateThresholds | None = None) -> None:
        self.thresholds = thresholds or GateThresholds()

    def evaluate(
        self,
        current: BaselineReport,
        baseline: BaselineReport | None = None,
        scale_report=None,
        shadow_results: list | None = None,
    ) -> RegressionGateReport:
        checks: list[GateCheck] = []

        # Gate 1 — Functional: scenario audit pass + no stale leaks
        checks.extend(self._check_functional(current))

        # Gate 2 — Latency: absolute p95 + regression vs baseline
        checks.extend(self._check_latency(current, baseline))

        # Gate 3 — Scaling: compile slope
        if scale_report is not None:
            checks.extend(self._check_scale(scale_report))

        # Gate 4 — Shadow / fallback
        if shadow_results is not None:
            checks.extend(self._check_shadow(shadow_results))

        overall = all(c.passed for c in checks)
        return RegressionGateReport(
            timestamp=make_timestamp(),
            overall_pass=overall,
            checks=checks,
        )

    # ── Gate 1 ────────────────────────────────────────────────────

    def _check_functional(self, report: BaselineReport) -> list[GateCheck]:
        checks: list[GateCheck] = []
        for sr in report.scenario_results:
            name = sr.get("name", "unknown")
            audit = sr.get("audit_pass", False)
            stale = sr.get("stale_leak_count", 0)
            checks.append(GateCheck(
                name=f"functional.{name}.audit",
                passed=bool(audit),
                actual=1 if audit else 0,
                threshold=1,
                message=f"Audit {'passed' if audit else 'FAILED'} for {name}",
            ))
            checks.append(GateCheck(
                name=f"functional.{name}.stale_leak",
                passed=stale == 0,
                actual=stale,
                threshold=0,
                message=f"Stale leak count: {stale}" if stale else "No stale leaks",
            ))
        return checks

    # ── Gate 2 ────────────────────────────────────────────────────

    def _check_latency(
        self,
        current: BaselineReport,
        baseline: BaselineReport | None,
    ) -> list[GateCheck]:
        checks: list[GateCheck] = []
        durations = [e.duration_ms for e in current.hook_latencies]
        if not durations:
            checks.append(GateCheck(
                name="latency.data_available",
                passed=False,
                actual=0,
                threshold=1,
                message="No latency data available",
            ))
            return checks

        sorted_d = sorted(durations)
        p95 = round(_percentile(sorted_d, 95), 3)

        # Absolute p95 threshold
        checks.append(GateCheck(
            name="latency.p95_absolute",
            passed=p95 <= self.thresholds.latency_p95_max_ms,
            actual=p95,
            threshold=self.thresholds.latency_p95_max_ms,
            message=f"p95={p95}ms (max={self.thresholds.latency_p95_max_ms}ms)",
        ))

        # Regression vs baseline
        if baseline and baseline.hook_latencies:
            base_durations = sorted(e.duration_ms for e in baseline.hook_latencies)
            base_p95 = _percentile(base_durations, 95)
            if base_p95 > 0:
                regression_pct = round((p95 - base_p95) / base_p95, 4)
                max_reg = self.thresholds.latency_p95_regression_pct
                checks.append(GateCheck(
                    name="latency.p95_regression",
                    passed=regression_pct <= max_reg,
                    actual=regression_pct,
                    threshold=max_reg,
                    message=f"p95 change: {regression_pct:.1%} (max regression={max_reg:.0%})",
                ))

        return checks

    # ── Gate 3 ────────────────────────────────────────────────────

    def _check_scale(self, scale_report) -> list[GateCheck]:
        points = scale_report.points
        if len(points) < 2:
            return []

        xs = [p.obligation_count for p in points]
        ys = [p.compile_duration_ms for p in points]
        slope = round(_linear_slope(xs, ys), 3)

        return [GateCheck(
            name="scale.compile_slope",
            passed=slope <= self.thresholds.scale_slope_max,
            actual=slope,
            threshold=self.thresholds.scale_slope_max,
            message=f"Compile slope: {slope} ms/obligation (max={self.thresholds.scale_slope_max})",
        )]

    # ── Gate 4 ────────────────────────────────────────────────────

    def _check_shadow(self, shadow_results: list) -> list[GateCheck]:
        if not shadow_results:
            return [GateCheck(
                name="shadow.critical_diffs",
                passed=True,
                actual=0,
                threshold=self.thresholds.shadow_critical_diff_max,
                message="No shadow results to check",
            )]

        # Support both CompileDiffResult objects and dicts
        critical_count = 0
        for d in shadow_results:
            if isinstance(d, dict):
                if not d.get("audit_match", True):
                    critical_count += 1
            elif hasattr(d, "has_critical_diff") and d.has_critical_diff:
                critical_count += 1

        return [GateCheck(
            name="shadow.critical_diffs",
            passed=critical_count <= self.thresholds.shadow_critical_diff_max,
            actual=critical_count,
            threshold=self.thresholds.shadow_critical_diff_max,
            message=f"Critical shadow diffs: {critical_count}",
        )]


def generate_judgment_report(report: RegressionGateReport) -> str:
    """Generate markdown judgment report explaining each gate check."""
    status = "PASS" if report.overall_pass else "FAIL"
    lines = [
        "# Regression Gate Judgment",
        "",
        f"**Overall**: {status}",
        f"**Timestamp**: {report.timestamp}",
        "",
        "## Check Details",
        "| Check | Result | Actual | Threshold | Note |",
        "|-------|--------|--------|-----------|------|",
    ]
    for check in report.checks:
        mark = "\u2705 PASS" if check.passed else "\u274c FAIL"
        lines.append(
            f"| {check.name} | {mark} | {check.actual} | {check.threshold} | {check.message} |"
        )
    lines.append("")

    failed = [c for c in report.checks if not c.passed]
    if failed:
        lines.append("## Failed Checks")
        for c in failed:
            lines.append(
                f"- **{c.name}**: {c.message} (actual={c.actual}, threshold={c.threshold})"
            )
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def load_baseline(path: str) -> BaselineReport | None:
    """Load a baseline report from a JSON file."""
    p = Path(path)
    if not p.is_file():
        return None
    try:
        with p.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
        return BaselineReport(
            timestamp=data.get("timestamp", ""),
            runtime_mode=data.get("runtime_mode", "legacy"),
            hook_latencies=[
                HookLatencyEntry(
                    hook_name=e["hook_name"],
                    duration_ms=e["duration_ms"],
                )
                for e in data.get("hook_latencies", [])
            ],
            session_size=data.get("session_size", 0),
            obligation_count=data.get("obligation_count", 0),
            evidence_count=data.get("evidence_count", 0),
            assertion_count=data.get("assertion_count", 0),
            compile_duration_ms=data.get("compile_duration_ms", 0.0),
            token_estimate=data.get("token_estimate", 0),
            scenario_results=data.get("scenario_results", []),
        )
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def save_gate_report(report: RegressionGateReport, reports_dir: str) -> str:
    """Write gate report JSON and return the file path."""
    dir_path = Path(reports_dir)
    dir_path.mkdir(parents=True, exist_ok=True)
    ts = report.timestamp.replace(":", "-").replace(".", "-")
    filename = f"gate_{ts}.json"
    out_path = dir_path / filename
    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(report.to_dict(), fh, indent=2, ensure_ascii=False)
    return str(out_path)

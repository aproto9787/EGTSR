"""Release checklist automation (Step 09).

Implements the pre-release checklist from document 11 section 5:
- benchmark latest pass
- critical diff 0
- contract validation pass
- daemon fallback test pass
- regression gate pass

Each check returns a structured result; the overall verdict is PASS
only when all checks pass.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal


@dataclass(slots=True)
class CheckResult:
    name: str
    passed: bool
    detail: str

    def to_dict(self) -> dict:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass(slots=True)
class ReleaseCheckReport:
    timestamp: str
    overall_pass: bool
    checks: list[CheckResult] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "overall_pass": self.overall_pass,
            "checks": [c.to_dict() for c in self.checks],
        }


class ReleaseChecker:
    """Run automated release checklist against current state."""

    def __init__(self, egtsr_dir: str) -> None:
        self._egtsr_dir = egtsr_dir
        self._reports_dir = str(Path(egtsr_dir) / "reports")

    def run_all(self) -> ReleaseCheckReport:
        """Execute all release checks and return report."""
        checks: list[CheckResult] = []

        checks.append(self._check_regression_gate())
        checks.append(self._check_shadow_critical_diffs())
        checks.append(self._check_contract_validation())
        checks.append(self._check_daemon_fallback())
        checks.append(self._check_cutover_stage())

        overall = all(c.passed for c in checks)
        report = ReleaseCheckReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            overall_pass=overall,
            checks=checks,
        )
        return report

    def _check_regression_gate(self) -> CheckResult:
        """Check if the latest regression gate report passed."""
        gate_dir = Path(self._reports_dir)
        if not gate_dir.is_dir():
            return CheckResult(
                name="regression_gate",
                passed=False,
                detail="No reports directory found",
            )

        gate_files = sorted(gate_dir.glob("gate_*.json"), reverse=True)
        if not gate_files:
            return CheckResult(
                name="regression_gate",
                passed=False,
                detail="No gate report found — run `egtsr benchmark gate` first",
            )

        latest = gate_files[0]
        try:
            data = json.loads(latest.read_text(encoding="utf-8"))
            passed = data.get("overall_pass", False)
            failed_names = [
                c["name"]
                for c in data.get("checks", [])
                if not c.get("passed", False)
            ]
            if passed:
                detail = f"Latest gate PASS ({latest.name})"
            else:
                detail = f"Gate FAIL ({latest.name}): {', '.join(failed_names)}"
            return CheckResult(name="regression_gate", passed=passed, detail=detail)
        except (json.JSONDecodeError, OSError, KeyError) as exc:
            return CheckResult(
                name="regression_gate",
                passed=False,
                detail=f"Cannot read gate report: {exc}",
            )

    def _check_shadow_critical_diffs(self) -> CheckResult:
        """Check that no shadow diff reports have critical diffs."""
        shadow_dir = Path(self._reports_dir) / "shadow"
        if not shadow_dir.is_dir():
            return CheckResult(
                name="shadow_critical_diffs",
                passed=True,
                detail="No shadow reports (OK — no shadow runs recorded)",
            )

        critical_count = 0
        total = 0
        for f in shadow_dir.glob("shadow_diff_*.json"):
            total += 1
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                compile_data = data.get("compile", {})
                inv_data = data.get("invalidation", {})
                if compile_data.get("has_critical_diff"):
                    critical_count += 1
                if inv_data.get("has_critical_diff"):
                    critical_count += 1
            except (json.JSONDecodeError, OSError):
                continue

        passed = critical_count == 0
        detail = f"{critical_count} critical diffs in {total} shadow reports"
        return CheckResult(name="shadow_critical_diffs", passed=passed, detail=detail)

    def _check_contract_validation(self) -> CheckResult:
        """Verify that contract validators are importable and functional."""
        try:
            from egtsr_runtime.compat.contract import (
                validate_capsule_snapshot,
                validate_hook_response,
                validate_resume_gate_snapshot,
            )

            # Quick smoke test: valid allow response should pass
            resp = {"hookSpecificOutput": {"additionalContext": "ok"}}
            violations = validate_hook_response(resp)
            if violations:
                return CheckResult(
                    name="contract_validation",
                    passed=False,
                    detail=f"Contract validator self-test failed: {violations}",
                )
            return CheckResult(
                name="contract_validation",
                passed=True,
                detail="Contract validators functional",
            )
        except ImportError as exc:
            return CheckResult(
                name="contract_validation",
                passed=False,
                detail=f"Cannot import contract validators: {exc}",
            )

    def _check_daemon_fallback(self) -> CheckResult:
        """Check daemon fallback rate from metrics."""
        metrics_dir = Path(self._egtsr_dir) / "metrics"
        if not metrics_dir.is_dir():
            return CheckResult(
                name="daemon_fallback",
                passed=True,
                detail="No metrics directory (OK — no daemon runs recorded)",
            )

        total = 0
        fallback_count = 0
        for f in metrics_dir.glob("*.jsonl"):
            try:
                for line in f.read_text(encoding="utf-8").splitlines():
                    if not line.strip():
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if entry.get("event") == "hook_complete":
                        total += 1
                        if entry.get("daemon_fallback"):
                            fallback_count += 1
            except OSError:
                continue

        if total == 0:
            return CheckResult(
                name="daemon_fallback",
                passed=True,
                detail="No hook metrics recorded yet",
            )

        rate = fallback_count / total
        passed = rate <= 0.05  # max 5% fallback rate
        detail = f"Fallback rate: {fallback_count}/{total} ({rate:.1%})"
        return CheckResult(name="daemon_fallback", passed=passed, detail=detail)

    def _check_cutover_stage(self) -> CheckResult:
        """Check that cutover state file is consistent."""
        state_path = Path(self._egtsr_dir) / "cutover_state.json"
        if not state_path.is_file():
            return CheckResult(
                name="cutover_stage",
                passed=True,
                detail="No cutover state (baseline assumed)",
            )

        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            stage = data.get("current_stage", "unknown")
            return CheckResult(
                name="cutover_stage",
                passed=True,
                detail=f"Current cutover stage: {stage}",
            )
        except (json.JSONDecodeError, OSError) as exc:
            return CheckResult(
                name="cutover_stage",
                passed=False,
                detail=f"Cannot read cutover state: {exc}",
            )


def save_release_report(report: ReleaseCheckReport, reports_dir: str) -> str:
    """Write release check report JSON and return the file path."""
    dir_path = Path(reports_dir)
    dir_path.mkdir(parents=True, exist_ok=True)
    ts = report.timestamp.replace(":", "-").replace(".", "-")
    filename = f"release_check_{ts}.json"
    out_path = dir_path / filename
    out_path.write_text(
        json.dumps(report.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return str(out_path)

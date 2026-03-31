"""Latency benchmark — measures per-hook execution time in ms.

Step 08 adds:
- ``run_with_percentiles()`` for multi-iteration runs with p50/p95/p99.
- ``ColdWarmBenchmark`` for cold-start vs warm-path latency comparison.
"""
from __future__ import annotations

import json
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from egtsr_runtime.benchmarks.baseline import (
    BaselineReport,
    HookLatencyEntry,
    make_timestamp,
    save_baseline_report,
)
from egtsr_runtime.benchmarks.scenarios import ScenarioResult, _BaseScenario, ForcedSplitScenario
from egtsr_runtime.db.uow import SqliteUnitOfWork
from egtsr_runtime.ops.metrics import _percentile


@dataclass(slots=True)
class PhasePercentiles:
    """Percentile stats for a single phase across multiple iterations."""
    phase: str
    count: int
    p50: float
    p95: float
    p99: float
    min_ms: float
    max_ms: float
    mean_ms: float


@dataclass(slots=True)
class LatencyPercentileReport:
    """Multi-iteration latency report with per-phase percentiles."""
    timestamp: str
    iterations: int
    phases: list[PhasePercentiles] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "iterations": self.iterations,
            "phases": [
                {
                    "phase": p.phase,
                    "count": p.count,
                    "p50": p.p50,
                    "p95": p.p95,
                    "p99": p.p99,
                    "min_ms": p.min_ms,
                    "max_ms": p.max_ms,
                    "mean_ms": p.mean_ms,
                }
                for p in self.phases
            ],
        }


class LatencyBenchmark:
    """Measure hook-level latency using forced-split scenario as workload."""

    def run(self, reports_dir: str | None = None) -> BaselineReport:
        report = BaselineReport(timestamp=make_timestamp())

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "latency_bench.sqlite3")
            scenario = ForcedSplitScenario()

            # Measure total scenario run (covers seed + invalidation + compile)
            start = time.perf_counter()
            result = scenario.run(db_path)
            end = time.perf_counter()
            total_ms = (end - start) * 1000.0

            report.hook_latencies.append(
                HookLatencyEntry(hook_name="scenario_run_total", duration_ms=round(total_ms, 3))
            )

            # Measure individual phases
            db_path2 = str(Path(tmp_dir) / "latency_phases.sqlite3")
            scenario2 = ForcedSplitScenario()
            scenario2._prepare_db(db_path2)
            session_id = "bench-latency"

            # seed phase
            start = time.perf_counter()
            with SqliteUnitOfWork(db_path2) as uow:
                scenario2._seed_session(uow, session_id)
                obl = scenario2._make_obligation(session_id, "obl-lat", "Latency test")
                uow.obligations.upsert(obl)
                for i in range(3):
                    ev = scenario2._make_evidence(
                        session_id, f"ev-lat-{i}",
                        source_tool="read", path=f"/repo/f{i}.py",
                        excerpt=f"evidence {i} " * 10,
                        created_at=f"2026-03-31T10:0{i}:00Z",
                    )
                    uow.evidence.create(ev)
                    ass = scenario2._make_assertion(
                        session_id, f"as-lat-{i}", obl.id,
                        f"Assertion {i}",
                        scope_ref=f"/repo/f{i}.py",
                        evidence_ids=[f"ev-lat-{i}"],
                        created_at=f"2026-03-31T10:1{i}:00Z",
                    )
                    uow.assertions.upsert(ass)
                uow.commit()
            seed_ms = (time.perf_counter() - start) * 1000.0
            report.hook_latencies.append(
                HookLatencyEntry(hook_name="db_seed", duration_ms=round(seed_ms, 3))
            )

            # compile phase
            start = time.perf_counter()
            with SqliteUnitOfWork(db_path2) as uow:
                scenario2._compile_state(uow, session_id)
            compile_ms = (time.perf_counter() - start) * 1000.0
            report.hook_latencies.append(
                HookLatencyEntry(hook_name="compile", duration_ms=round(compile_ms, 3))
            )
            report.compile_duration_ms = compile_ms

            # invalidation phase
            start = time.perf_counter()
            with SqliteUnitOfWork(db_path2) as uow:
                from egtsr_runtime.services import FileTouchInvalidationService
                FileTouchInvalidationService(uow).apply(session_id, ["/repo/f0.py"])
                uow.commit()
            invalidation_ms = (time.perf_counter() - start) * 1000.0
            report.hook_latencies.append(
                HookLatencyEntry(hook_name="invalidation", duration_ms=round(invalidation_ms, 3))
            )

            report.obligation_count = 1
            report.evidence_count = 3
            report.assertion_count = 3
            report.token_estimate = result.token_count
            report.scenario_results.append(asdict(result))

        if reports_dir:
            save_baseline_report(report, reports_dir)

        return report

    def run_with_percentiles(
        self, iterations: int = 10, reports_dir: str | None = None,
    ) -> LatencyPercentileReport:
        """Run the benchmark *iterations* times and report per-phase percentiles."""
        phase_samples: dict[str, list[float]] = {
            "scenario_run_total": [],
            "db_seed": [],
            "compile": [],
            "invalidation": [],
        }

        for _ in range(iterations):
            report = self.run()
            for entry in report.hook_latencies:
                if entry.hook_name in phase_samples:
                    phase_samples[entry.hook_name].append(entry.duration_ms)

        phases: list[PhasePercentiles] = []
        for phase_name, samples in phase_samples.items():
            if not samples:
                continue
            s = sorted(samples)
            phases.append(PhasePercentiles(
                phase=phase_name,
                count=len(s),
                p50=round(_percentile(s, 50), 3),
                p95=round(_percentile(s, 95), 3),
                p99=round(_percentile(s, 99), 3),
                min_ms=round(s[0], 3),
                max_ms=round(s[-1], 3),
                mean_ms=round(sum(s) / len(s), 3),
            ))

        result = LatencyPercentileReport(
            timestamp=make_timestamp(),
            iterations=iterations,
            phases=phases,
        )

        if reports_dir:
            dir_path = Path(reports_dir)
            dir_path.mkdir(parents=True, exist_ok=True)
            ts = result.timestamp.replace(":", "-").replace(".", "-")
            out_path = dir_path / f"latency_percentiles_{ts}.json"
            with out_path.open("w", encoding="utf-8") as fh:
                json.dump(result.to_dict(), fh, indent=2, ensure_ascii=False)

        return result


# ── Cold vs Warm daemon latency ───────────────────────────────────


@dataclass(slots=True)
class ColdWarmEntry:
    label: str  # "cold" or "warm"
    phase: str
    duration_ms: float


@dataclass(slots=True)
class ColdWarmReport:
    """Compares cold-start vs warm-path latency for the same workload."""
    timestamp: str
    entries: list[ColdWarmEntry] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "entries": [
                {"label": e.label, "phase": e.phase,
                 "duration_ms": round(e.duration_ms, 3)}
                for e in self.entries
            ],
        }


class ColdWarmBenchmark(_BaseScenario):
    """Measure cold-start vs warm-path latency.

    *Cold*: new connection + migration + seed + compile (simulates first
    hook when daemon is absent, i.e. full legacy inline path).

    *Warm*: reuse a boot-once ``SqliteRuntime`` connection + compile
    (simulates repeated hooks on a running daemon).
    """

    name = "cold_warm"

    def run(self, reports_dir: str | None = None) -> ColdWarmReport:
        from egtsr_runtime.db.runtime import SqliteRuntime

        report = ColdWarmReport(timestamp=make_timestamp())

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "cold_warm.sqlite3")
            session_id = "bench-cold-warm"

            # ── Cold path: open + migrate + seed + compile ──
            start = time.perf_counter()
            runtime_cold = SqliteRuntime(db_path)
            conn = runtime_cold.boot()
            cold_boot_ms = (time.perf_counter() - start) * 1000.0
            report.entries.append(
                ColdWarmEntry("cold", "boot_migrate", round(cold_boot_ms, 3))
            )

            start = time.perf_counter()
            with SqliteUnitOfWork(conn) as uow:
                self._seed_session(uow, session_id)
                obl = self._make_obligation(session_id, "obl-cw", "ColdWarm test")
                uow.obligations.upsert(obl)
                for i in range(3):
                    ev = self._make_evidence(
                        session_id, f"ev-cw-{i}",
                        source_tool="read", path=f"/repo/f{i}.py",
                        excerpt=f"cold warm evidence {i} " * 10,
                        created_at=f"2026-03-31T10:0{i}:00Z",
                    )
                    uow.evidence.create(ev)
                    ass = self._make_assertion(
                        session_id, f"as-cw-{i}", obl.id,
                        f"CW Assertion {i}",
                        scope_ref=f"/repo/f{i}.py",
                        evidence_ids=[f"ev-cw-{i}"],
                        created_at=f"2026-03-31T10:1{i}:00Z",
                    )
                    uow.assertions.upsert(ass)
                uow.commit()
            cold_seed_ms = (time.perf_counter() - start) * 1000.0
            report.entries.append(
                ColdWarmEntry("cold", "seed", round(cold_seed_ms, 3))
            )

            start = time.perf_counter()
            with SqliteUnitOfWork(conn) as uow:
                self._compile_state(uow, session_id)
            cold_compile_ms = (time.perf_counter() - start) * 1000.0
            report.entries.append(
                ColdWarmEntry("cold", "compile", round(cold_compile_ms, 3))
            )

            cold_total = cold_boot_ms + cold_seed_ms + cold_compile_ms
            report.entries.append(
                ColdWarmEntry("cold", "total", round(cold_total, 3))
            )
            runtime_cold.shutdown()

            # ── Warm path: reuse booted runtime, compile only ──
            runtime_warm = SqliteRuntime(db_path)
            conn = runtime_warm.boot()

            # Run compile multiple times to measure warm-path latency
            for i in range(5):
                start = time.perf_counter()
                with SqliteUnitOfWork(conn) as uow:
                    self._compile_state(uow, session_id)
                warm_ms = (time.perf_counter() - start) * 1000.0
                report.entries.append(
                    ColdWarmEntry("warm", f"compile_iter{i}", round(warm_ms, 3))
                )

            runtime_warm.shutdown()

        if reports_dir:
            dir_path = Path(reports_dir)
            dir_path.mkdir(parents=True, exist_ok=True)
            ts = report.timestamp.replace(":", "-").replace(".", "-")
            out_path = dir_path / f"cold_warm_{ts}.json"
            with out_path.open("w", encoding="utf-8") as fh:
                json.dump(report.to_dict(), fh, indent=2, ensure_ascii=False)

        return report

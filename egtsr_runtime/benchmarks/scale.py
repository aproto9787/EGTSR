"""Scale benchmark — latency trend across growing session sizes.

Step 08 adds slope calculation for compile and invalidation duration
as a function of session size (obligations).
"""
from __future__ import annotations

import json
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

from egtsr_runtime.benchmarks.baseline import make_timestamp
from egtsr_runtime.benchmarks.scenarios import _BaseScenario
from egtsr_runtime.db.uow import SqliteUnitOfWork
from egtsr_runtime.enums import ObligationStatus


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


@dataclass(slots=True)
class ScalePoint:
    obligation_count: int
    evidence_count: int
    assertion_count: int
    compile_duration_ms: float
    invalidation_duration_ms: float
    token_estimate: int


@dataclass(slots=True)
class ScaleReport:
    timestamp: str
    runtime_mode: str = "legacy"
    points: list[ScalePoint] = field(default_factory=list)
    compile_slope: float = 0.0
    invalidation_slope: float = 0.0

    def compute_slopes(self) -> None:
        """Calculate linear regression slopes from collected points."""
        if len(self.points) < 2:
            return
        xs = [p.obligation_count for p in self.points]
        self.compile_slope = round(
            _linear_slope(xs, [p.compile_duration_ms for p in self.points]), 3
        )
        self.invalidation_slope = round(
            _linear_slope(xs, [p.invalidation_duration_ms for p in self.points]), 3
        )

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "runtime_mode": self.runtime_mode,
            "compile_slope_ms_per_obl": self.compile_slope,
            "invalidation_slope_ms_per_obl": self.invalidation_slope,
            "points": [
                {
                    "obligation_count": p.obligation_count,
                    "evidence_count": p.evidence_count,
                    "assertion_count": p.assertion_count,
                    "compile_duration_ms": round(p.compile_duration_ms, 3),
                    "invalidation_duration_ms": round(p.invalidation_duration_ms, 3),
                    "token_estimate": p.token_estimate,
                }
                for p in self.points
            ],
        }


class ScaleBenchmark(_BaseScenario):
    """Run compile + invalidation at increasing session sizes."""

    name = "scale"

    def __init__(self, sizes: list[int] | None = None) -> None:
        super().__init__()
        self.sizes = sizes or [10, 100, 1000]

    def run_scale(self, reports_dir: str | None = None) -> ScaleReport:
        report = ScaleReport(timestamp=make_timestamp())

        with tempfile.TemporaryDirectory() as tmp_dir:
            for size in self.sizes:
                point = self._measure_at_size(tmp_dir, size)
                report.points.append(point)

        report.compute_slopes()

        if reports_dir:
            dir_path = Path(reports_dir)
            dir_path.mkdir(parents=True, exist_ok=True)
            ts = report.timestamp.replace(":", "-").replace(".", "-")
            out_path = dir_path / f"scale_{ts}.json"
            with out_path.open("w", encoding="utf-8") as fh:
                json.dump(report.to_dict(), fh, indent=2, ensure_ascii=False)

        return report

    def _measure_at_size(self, tmp_dir: str, obl_count: int) -> ScalePoint:
        db_path = str(Path(tmp_dir) / f"scale_{obl_count}.sqlite3")
        self._prepare_db(db_path)
        session_id = f"bench-scale-{obl_count}"
        evidence_total = 0
        assertion_total = 0

        # Seed
        with SqliteUnitOfWork(db_path) as uow:
            self._seed_session(uow, session_id)
            for i in range(obl_count):
                obl = self._make_obligation(
                    session_id, f"obl-s{i}", f"Scale obligation {i}",
                    status=ObligationStatus.OPEN,
                )
                uow.obligations.upsert(obl)
                for j in range(2):  # 2 evidence per obligation
                    ev_id = f"ev-s{i}-{j}"
                    path = f"/repo/mod{i}/f{j}.py"
                    ev = self._make_evidence(
                        session_id, ev_id,
                        source_tool="read", path=path,
                        excerpt=f"evidence for obl {i} file {j} " * 5,
                        created_at=f"2026-03-31T10:{i:02d}:{j:02d}Z",
                    )
                    uow.evidence.create(ev)
                    evidence_total += 1

                    ass = self._make_assertion(
                        session_id, f"as-s{i}-{j}", obl.id,
                        f"Assertion {i}-{j}",
                        scope_ref=path,
                        evidence_ids=[ev_id],
                        created_at=f"2026-03-31T10:{i:02d}:{j+30:02d}Z",
                    )
                    uow.assertions.upsert(ass)
                    assertion_total += 1
            uow.commit()

        # Compile
        start = time.perf_counter()
        with SqliteUnitOfWork(db_path) as uow:
            capsule, audit, *_ = self._compile_state(uow, session_id)
        compile_ms = (time.perf_counter() - start) * 1000.0

        # Invalidation
        start = time.perf_counter()
        with SqliteUnitOfWork(db_path) as uow:
            from egtsr_runtime.services import FileTouchInvalidationService
            FileTouchInvalidationService(uow).apply(session_id, ["/repo/mod0/f0.py"])
            uow.commit()
        invalidation_ms = (time.perf_counter() - start) * 1000.0

        return ScalePoint(
            obligation_count=obl_count,
            evidence_count=evidence_total,
            assertion_count=assertion_total,
            compile_duration_ms=compile_ms,
            invalidation_duration_ms=invalidation_ms,
            token_estimate=capsule.token_estimate,
        )

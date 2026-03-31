"""Migration/backfill benchmark — measures migration and projection rebuild time.

Spec ref: 09_Performance_Observability_and_Benchmark Section 4B.
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


@dataclass(slots=True)
class MigrationBenchEntry:
    phase: str
    duration_ms: float
    detail: str = ""


@dataclass(slots=True)
class MigrationBenchReport:
    """Report for migration + backfill benchmark."""
    timestamp: str
    entries: list[MigrationBenchEntry] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "entries": [
                {
                    "phase": e.phase,
                    "duration_ms": round(e.duration_ms, 3),
                    "detail": e.detail,
                }
                for e in self.entries
            ],
        }


class MigrationBenchmark(_BaseScenario):
    """Measure migration execution time and projection backfill time."""

    name = "migration_backfill"

    def run_bench(self, reports_dir: str | None = None) -> MigrationBenchReport:
        from egtsr_runtime.db.connection import get_connection
        from egtsr_runtime.db.migrations import run_migrations
        from egtsr_runtime.services.projection_backfill import rebuild_session_projections

        report = MigrationBenchReport(timestamp=make_timestamp())

        with tempfile.TemporaryDirectory() as tmp_dir:
            db_path = str(Path(tmp_dir) / "migration_bench.sqlite3")

            # Phase 1: cold migration on empty DB
            start = time.perf_counter()
            conn = get_connection(db_path, check_same_thread=False)
            run_migrations(conn)
            migration_ms = (time.perf_counter() - start) * 1000.0
            report.entries.append(MigrationBenchEntry(
                "cold_migration", round(migration_ms, 3),
                detail="Fresh DB: connection + all migrations",
            ))

            # Phase 2: idempotent re-migration (should be near-zero)
            start = time.perf_counter()
            run_migrations(conn)
            re_migration_ms = (time.perf_counter() - start) * 1000.0
            report.entries.append(MigrationBenchEntry(
                "idempotent_migration", round(re_migration_ms, 3),
                detail="Re-run migrations on already-migrated DB",
            ))

            # Seed data for backfill benchmark
            session_id = "bench-migration"
            obl_count = 10
            with SqliteUnitOfWork(conn) as uow:
                self._seed_session(uow, session_id)
                for i in range(obl_count):
                    obl = self._make_obligation(
                        session_id, f"obl-m{i}", f"Migration obl {i}",
                        status=ObligationStatus.OPEN,
                    )
                    uow.obligations.upsert(obl)
                    for j in range(3):  # 3 evidence per obligation
                        ev_id = f"ev-m{i}-{j}"
                        path = f"/repo/mod{i}/f{j}.py"
                        ev = self._make_evidence(
                            session_id, ev_id,
                            source_tool="read", path=path,
                            excerpt=f"migration bench evidence {i}-{j} " * 5,
                            created_at=f"2026-03-31T10:{i:02d}:{j:02d}Z",
                        )
                        uow.evidence.create(ev)
                        ass = self._make_assertion(
                            session_id, f"as-m{i}-{j}", obl.id,
                            f"Migration assertion {i}-{j}",
                            scope_ref=path,
                            evidence_ids=[ev_id],
                            created_at=f"2026-03-31T10:{i:02d}:{j+30:02d}Z",
                        )
                        uow.assertions.upsert(ass)
                uow.commit()

            # Phase 3: projection backfill
            start = time.perf_counter()
            rebuild_session_projections(conn, session_id)
            conn.commit()
            backfill_ms = (time.perf_counter() - start) * 1000.0
            report.entries.append(MigrationBenchEntry(
                "projection_backfill", round(backfill_ms, 3),
                detail=f"Rebuild projections for {obl_count} obligations, "
                       f"{obl_count * 3} evidence/assertions",
            ))

            # Phase 4: idempotent backfill (rebuild on already-filled projections)
            start = time.perf_counter()
            rebuild_session_projections(conn, session_id)
            conn.commit()
            re_backfill_ms = (time.perf_counter() - start) * 1000.0
            report.entries.append(MigrationBenchEntry(
                "idempotent_backfill", round(re_backfill_ms, 3),
                detail="Re-run backfill on already-populated projections",
            ))

            conn.close()

        if reports_dir:
            dir_path = Path(reports_dir)
            dir_path.mkdir(parents=True, exist_ok=True)
            ts = report.timestamp.replace(":", "-").replace(".", "-")
            out_path = dir_path / f"migration_backfill_{ts}.json"
            with out_path.open("w", encoding="utf-8") as fh:
                json.dump(report.to_dict(), fh, indent=2, ensure_ascii=False)

        return report

from __future__ import annotations

import tempfile
from pathlib import Path

from egtsr_runtime.benchmarks.scenarios import (
    ForcedSplitScenario,
    RepeatedFailureScenario,
    ScenarioResult,
    StaleInjectionScenario,
)


class BenchmarkRunner:
    def run_all(self) -> list[ScenarioResult]:
        """Run all 3 scenarios and return results."""
        results: list[ScenarioResult] = []
        with tempfile.TemporaryDirectory() as tmp_dir:
            for scenario_class in (ForcedSplitScenario, StaleInjectionScenario, RepeatedFailureScenario):
                scenario = scenario_class()
                db_path = Path(tmp_dir) / f"{scenario.name}.sqlite3"
                results.append(scenario.run(str(db_path)))
        return results

    def run_same_budget_comparison(self, budget: int = 900) -> dict:
        """Run 3-way comparison: raw tokens vs naive vs EGTSR."""
        comparison: dict[str, dict[str, int]] = {}
        with tempfile.TemporaryDirectory() as tmp_dir:
            for scenario_class in (ForcedSplitScenario, StaleInjectionScenario, RepeatedFailureScenario):
                scenario = scenario_class(token_budget=budget)
                db_path = Path(tmp_dir) / f"{scenario.name}-budget.sqlite3"
                result = scenario.run(str(db_path))
                comparison[result.name] = {
                    "raw": int(result.details.get("raw_token_count", 0)),
                    "naive": int(result.details.get("naive_token_count", 0)),
                    "egtsr": result.token_count,
                }
        return comparison

from __future__ import annotations

from egtsr_runtime.benchmarks.scenarios import ScenarioResult


class GoNoGoEvaluator:
    def evaluate(self, results: list[ScenarioResult]) -> str:
        """Return 'continue', 'shrink', or 'stop'.

        Stop: any audit_pass=False OR stale_leak_count>0 OR resume_safety=False
        Shrink: all safe but token savings < 20%
        Continue: all safe and token savings >= 20%
        """
        if any((not item.audit_pass) or item.stale_leak_count > 0 or (not item.resume_safety) for item in results):
            return "stop"
        average_savings = self._average_token_savings(results)
        if average_savings < 0.2:
            return "shrink"
        return "continue"

    def _average_token_savings(self, results: list[ScenarioResult]) -> float:
        if not results:
            return 0.0
        savings = [self._token_savings(item) for item in results]
        return sum(savings) / len(savings)

    @staticmethod
    def _token_savings(result: ScenarioResult) -> float:
        raw_tokens = int(result.details.get("raw_token_count", 0) or 0)
        if raw_tokens <= 0:
            raw_tokens = int(result.details.get("naive_token_count", 0) or 0)
        if raw_tokens <= 0:
            return 0.0
        return max(0.0, (raw_tokens - result.token_count) / raw_tokens)

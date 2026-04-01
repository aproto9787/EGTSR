from __future__ import annotations

import csv
import io
from dataclasses import asdict

from egtsr_runtime.benchmarks.scenarios import ScenarioResult


class BenchmarkReporter:
    def generate_csv(self, results: list[ScenarioResult], comparison: dict) -> str:
        """Generate CSV report string."""
        output = io.StringIO()
        fieldnames = [
            "scenario",
            "executed",
            "audit_pass",
            "stale_leak_count",
            "token_count",
            "resume_safety",
            "obligation_count",
            "evidence_count",
            "failed_families",
            "raw_tokens",
            "naive_tokens",
            "egtsr_tokens",
        ]
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            method_counts = comparison.get(result.name, {})
            writer.writerow(
                {
                    "scenario": result.name,
                    "executed": result.executed,
                    "audit_pass": result.audit_pass,
                    "stale_leak_count": result.stale_leak_count,
                    "token_count": result.token_count,
                    "resume_safety": result.resume_safety,
                    "obligation_count": result.obligation_count,
                    "evidence_count": result.evidence_count,
                    "failed_families": result.failed_families,
                    "raw_tokens": method_counts.get("raw", result.details.get("raw_token_count", 0)),
                    "naive_tokens": method_counts.get("naive", result.details.get("naive_token_count", 0)),
                    "egtsr_tokens": method_counts.get("egtsr", result.token_count),
                }
            )
        return output.getvalue()

    def generate_json(self, results: list[ScenarioResult], comparison: dict, verdict: str) -> dict:
        """Generate JSON report dict."""
        scenario_rows = []
        savings = []
        for result in results:
            row = asdict(result)
            row["comparison"] = comparison.get(
                result.name,
                {
                    "raw": result.details.get("raw_token_count", 0),
                    "naive": result.details.get("naive_token_count", 0),
                    "egtsr": result.token_count,
                },
            )
            scenario_rows.append(row)
            savings.append(float(result.details.get("token_savings_pct", 0.0)))
        average_savings = sum(savings) / len(savings) if savings else 0.0
        return {
            "verdict": verdict,
            "scenarios": scenario_rows,
            "comparison": comparison,
            "summary": {
                "scenario_count": len(results),
                "executed_count": sum(1 for item in results if item.executed),
                "audit_pass_count": sum(1 for item in results if item.audit_pass),
                "average_token_savings_pct": round(average_savings, 4),
            },
        }

    def generate_memo(self, results: list[ScenarioResult], verdict: str) -> str:
        """Generate Go/No-Go markdown memo."""
        lines = ["# Step 11 Go/No-Go Memo", "", f"- Verdict: **{verdict}**", ""]
        for result in results:
            lines.append(f"## {result.name}")
            lines.append(f"- executed: {result.executed}")
            lines.append(f"- audit_pass: {result.audit_pass}")
            lines.append(f"- stale_leak_count: {result.stale_leak_count}")
            lines.append(f"- token_count: {result.token_count}")
            lines.append(f"- resume_safety: {result.resume_safety}")
            lines.append("")
        return "\n".join(lines).strip() + "\n"

    def generate_markdown_report(
        self,
        results: list[ScenarioResult],
        comparison: dict,
        verdict: str,
    ) -> str:
        """Generate full markdown benchmark report with summary table and Go/No-Go judgment."""
        lines = ["# EGTSR Benchmark Report", ""]

        # Summary table
        lines.append("## Summary")
        lines.append("| Scenario | Raw | Naive | EGTSR | Delta |")
        lines.append("|----------|-----|-------|-------|-------|")
        for result in results:
            method_counts = comparison.get(result.name, {})
            raw = int(method_counts.get("raw", result.details.get("raw_token_count", 0)))
            naive = int(method_counts.get("naive", result.details.get("naive_token_count", 0)))
            egtsr = int(method_counts.get("egtsr", result.token_count))
            savings_pct = float(result.details.get("token_savings_pct", 0.0))
            delta = f"{savings_pct:.1%}" if raw > 0 else "N/A"
            lines.append(f"| {result.name} | {raw} | {naive} | {egtsr} | {delta} |")
        lines.append("")

        # Go/No-Go Judgment
        verdict_label = {"continue": "Continue", "shrink": "Shrink", "stop": "Stop"}.get(
            verdict, verdict.title()
        )
        lines.append("## Go/No-Go Judgment")
        lines.append(f"**Verdict**: {verdict_label}")
        lines.append("")

        audit_fail_count = sum(1 for r in results if not r.audit_pass)
        stale_leak_total = sum(r.stale_leak_count for r in results)
        resume_unsafe_count = sum(1 for r in results if not r.resume_safety)

        lines.append("### Criteria")
        _p = lambda ok: "\u2705" if ok else "\u274c"  # noqa: E731
        lines.append(f"- Audit failures: {audit_fail_count} {_p(audit_fail_count == 0)}")
        lines.append(f"- Stale leak total: {stale_leak_total} {_p(stale_leak_total == 0)}")
        lines.append(f"- Resume unsafe: {resume_unsafe_count} {_p(resume_unsafe_count == 0)}")
        lines.append("")

        # Detailed Results
        lines.append("## Detailed Results")
        for result in results:
            lines.append(f"### {result.name}")
            lines.append(f"- executed: {result.executed}")
            lines.append(f"- audit_pass: {result.audit_pass}")
            lines.append(f"- stale_leak_count: {result.stale_leak_count}")
            lines.append(f"- token_count: {result.token_count}")
            lines.append(f"- resume_safety: {result.resume_safety}")
            lines.append(f"- obligation_count: {result.obligation_count}")
            lines.append(f"- evidence_count: {result.evidence_count}")
            lines.append(f"- failed_families: {result.failed_families}")
            lines.append("")
        return "\n".join(lines).strip() + "\n"

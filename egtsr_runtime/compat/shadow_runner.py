"""Shadow (dual-run) execution for compile and invalidation paths.

When ``runtime_mode == "shadow"``, both legacy and incremental paths run.
Results are diffed; the legacy result is always used for safety.
Diff reports are saved to ``.egtsr/reports/shadow/``.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from egtsr_runtime.compiler.audit import CapsuleAuditEngine
from egtsr_runtime.compiler.decision_compiler import DecisionCapsuleCompiler
from egtsr_runtime.compiler.decision_models import DecisionCompilerInput, DecisionCapsuleV0
from egtsr_runtime.compiler.incremental import IncrementalDecisionCompiler
from egtsr_runtime.services.invalidation import FileTouchInvalidationService, InvalidationResult

if TYPE_CHECKING:
    from egtsr_runtime.config import RuntimeConfig

log = logging.getLogger(__name__)

# ── Critical vs non-critical fields for diff classification ──────────
CRITICAL_FIELDS = frozenset({
    "allow_block",        # overall allow/block decision
    "audit_pass",
    "hard_fail_reasons",
    "open_obligation_ids",
    "rendered_obligation_ids",
    "live_stale_ticket_ids",
    "reopened_obligation_ids",
})

NON_CRITICAL_FIELDS = frozenset({
    "token_estimate",
    "warning_order",
    "rendered_text_whitespace",
})


# ── Compile shadow diff ──────────────────────────────────────────────

@dataclass(slots=True)
class ShadowDiffEntry:
    field_name: str
    legacy_value: object
    incremental_value: object
    is_critical: bool


@dataclass(slots=True)
class ShadowCompileResult:
    """Result of a shadow compile: legacy capsule + optional diff."""
    legacy_capsule: DecisionCapsuleV0
    incremental_capsule: DecisionCapsuleV0 | None = None
    critical_diffs: list[ShadowDiffEntry] = field(default_factory=list)
    non_critical_diffs: list[ShadowDiffEntry] = field(default_factory=list)
    has_critical_diff: bool = False
    error: str | None = None


class ShadowCompileRunner:
    """Run legacy + incremental compile and diff the results."""

    def __init__(self, uow, config: RuntimeConfig) -> None:
        self._uow = uow
        self._config = config
        self._legacy_compiler = DecisionCapsuleCompiler()
        self._audit_engine = CapsuleAuditEngine()

    def compile(self, session_id: str) -> ShadowCompileResult:
        """Execute dual compile.  Always returns legacy capsule for use."""
        # 1. Legacy compile (always primary)
        legacy_input = self._build_compiler_input(session_id)
        legacy_capsule = self._legacy_compiler.compile(legacy_input)

        # 2. Incremental compile (best-effort)
        incremental_capsule: DecisionCapsuleV0 | None = None
        error: str | None = None
        try:
            inc = IncrementalDecisionCompiler(self._uow, self._config.max_decision_tokens)
            inc_result = inc.compile(session_id)
            incremental_capsule = inc_result.capsule
        except Exception as exc:
            error = str(exc)
            log.warning("Shadow incremental compile failed: %s", exc)

        # 3. Diff
        result = ShadowCompileResult(
            legacy_capsule=legacy_capsule,
            incremental_capsule=incremental_capsule,
            error=error,
        )
        if incremental_capsule is not None:
            self._diff(result, legacy_capsule, incremental_capsule)

        return result

    def _diff(
        self,
        result: ShadowCompileResult,
        legacy: DecisionCapsuleV0,
        incremental: DecisionCapsuleV0,
    ) -> None:
        legacy_audit = self._audit_engine.audit(legacy)
        inc_audit = self._audit_engine.audit(incremental)

        # allow_block: the final allow/block decision derived from audit
        legacy_decision = "allow" if legacy_audit.passed else "block"
        inc_decision = "allow" if inc_audit.passed else "block"

        comparisons = [
            ("allow_block", legacy_decision, inc_decision, True),
            ("audit_pass", legacy_audit.passed, inc_audit.passed, True),
            ("hard_fail_reasons", list(legacy_audit.hard_fail_reasons), list(inc_audit.hard_fail_reasons), True),
            ("open_obligation_ids", sorted(legacy.audit_inputs.get("open_obligation_ids", [])),
             sorted(incremental.audit_inputs.get("open_obligation_ids", [])), True),
            ("rendered_obligation_ids", sorted(legacy.audit_inputs.get("rendered_obligation_ids", [])),
             sorted(incremental.audit_inputs.get("rendered_obligation_ids", [])), True),
            ("live_stale_ticket_ids", sorted(legacy.audit_inputs.get("live_stale_ticket_ids", [])),
             sorted(incremental.audit_inputs.get("live_stale_ticket_ids", [])), True),
            ("reopened_obligation_ids", sorted(legacy.audit_inputs.get("reopened_obligation_ids", [])),
             sorted(incremental.audit_inputs.get("reopened_obligation_ids", [])), True),
            ("token_estimate", legacy.token_estimate, incremental.token_estimate, False),
            ("block_count", len(legacy.obligation_blocks), len(incremental.obligation_blocks), False),
        ]

        for field_name, lv, iv, is_critical in comparisons:
            if lv != iv:
                entry = ShadowDiffEntry(
                    field_name=field_name,
                    legacy_value=lv,
                    incremental_value=iv,
                    is_critical=is_critical,
                )
                if is_critical:
                    result.critical_diffs.append(entry)
                else:
                    result.non_critical_diffs.append(entry)

        result.has_critical_diff = bool(result.critical_diffs)

    def _build_compiler_input(self, session_id: str) -> DecisionCompilerInput:
        return DecisionCompilerInput(
            session_id=session_id,
            token_budget=self._config.max_decision_tokens,
            open_obligations=self._uow.obligations.list_open(session_id),
            evidence=self._uow.evidence.list_for_session(session_id),
            assertions=self._uow.assertions.list_for_session(session_id),
            invalidation_tickets=self._uow.invalidations.list_for_session(session_id),
            attempt_families=self._uow.attempt_families.list_for_session(session_id),
        )


# ── Invalidation shadow diff ────────────────────────────────────────

@dataclass(slots=True)
class ShadowInvalidationResult:
    """Result of shadow invalidation: legacy result + optional diff."""
    legacy_result: InvalidationResult
    incremental_result: InvalidationResult | None = None
    critical_diffs: list[ShadowDiffEntry] = field(default_factory=list)
    has_critical_diff: bool = False
    error: str | None = None


class ShadowInvalidationRunner:
    """Run legacy + reverse-index invalidation and diff the results."""

    def __init__(self, uow) -> None:
        self._uow = uow

    def apply(self, session_id: str, changed_files: list[str]) -> ShadowInvalidationResult:
        """Execute dual invalidation.  Legacy result is always primary.

        The reverse-index path runs inside a SAVEPOINT that is always
        rolled back so it never mutates the DB.  This ensures the diff
        comparison is clean — the incremental path sees the same DB
        state as legacy, and legacy's writes are the only ones kept.
        """
        # 1. Reverse-index invalidation first, inside savepoint (rolled back)
        inc_result: InvalidationResult | None = None
        error: str | None = None
        conn = self._uow.conn
        try:
            conn.execute("SAVEPOINT shadow_inv")
            inc_svc = FileTouchInvalidationService(self._uow, enable_reverse_index=True)
            inc_result = inc_svc.apply(session_id, changed_files)
        except Exception as exc:
            error = str(exc)
            log.warning("Shadow reverse-index invalidation failed: %s", exc)
        finally:
            try:
                conn.execute("ROLLBACK TO SAVEPOINT shadow_inv")
                conn.execute("RELEASE SAVEPOINT shadow_inv")
            except Exception:
                pass  # savepoint may already be released on error

        # 2. Legacy invalidation (always primary — its writes are kept)
        legacy_svc = FileTouchInvalidationService(self._uow, enable_reverse_index=False)
        legacy_result = legacy_svc.apply(session_id, changed_files)

        result = ShadowInvalidationResult(
            legacy_result=legacy_result,
            incremental_result=inc_result,
            error=error,
        )

        if inc_result is not None:
            self._diff(result, legacy_result, inc_result)

        return result

    @staticmethod
    def _diff(
        result: ShadowInvalidationResult,
        legacy: InvalidationResult,
        incremental: InvalidationResult,
    ) -> None:
        comparisons = [
            ("stale_assertion_ids", sorted(legacy.stale_assertion_ids),
             sorted(incremental.stale_assertion_ids), True),
            ("reopened_obligation_ids", sorted(legacy.reopened_obligation_ids),
             sorted(incremental.reopened_obligation_ids), True),
            ("invalidation_ticket_count", len(legacy.invalidation_ticket_ids),
             len(incremental.invalidation_ticket_ids), False),
        ]

        for field_name, lv, iv, is_critical in comparisons:
            if lv != iv:
                entry = ShadowDiffEntry(
                    field_name=field_name,
                    legacy_value=lv,
                    incremental_value=iv,
                    is_critical=is_critical,
                )
                if is_critical:
                    result.critical_diffs.append(entry)
                else:
                    result.non_critical_diffs.append(entry)

        result.has_critical_diff = bool(result.critical_diffs)


# ── Report writer ────────────────────────────────────────────────────

def write_shadow_diff_report(
    reports_dir: str,
    *,
    hook_name: str,
    session_id: str,
    compile_result: ShadowCompileResult | None = None,
    invalidation_result: ShadowInvalidationResult | None = None,
) -> str | None:
    """Write shadow diff report JSON to ``.egtsr/reports/shadow/``.

    Returns the report file path, or ``None`` if no diffs to report.
    """
    has_data = False
    payload: dict = {
        "hook_name": hook_name,
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    if compile_result is not None:
        compile_payload: dict = {
            "has_critical_diff": compile_result.has_critical_diff,
            "error": compile_result.error,
            "critical_diffs": [_diff_entry_dict(d) for d in compile_result.critical_diffs],
            "non_critical_diffs": [_diff_entry_dict(d) for d in compile_result.non_critical_diffs],
        }
        payload["compile"] = compile_payload
        has_data = True

    if invalidation_result is not None:
        inv_payload: dict = {
            "has_critical_diff": invalidation_result.has_critical_diff,
            "error": invalidation_result.error,
            "critical_diffs": [_diff_entry_dict(d) for d in invalidation_result.critical_diffs],
        }
        payload["invalidation"] = inv_payload
        has_data = True

    if not has_data:
        return None

    shadow_dir = Path(reports_dir) / "shadow"
    shadow_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    filename = f"shadow_diff_{hook_name}_{ts}.json"
    out_path = shadow_dir / filename

    with out_path.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)

    if compile_result and compile_result.has_critical_diff:
        log.warning(
            "Shadow compile CRITICAL diff detected: %d diffs (session=%s)",
            len(compile_result.critical_diffs),
            session_id,
        )
    if invalidation_result and invalidation_result.has_critical_diff:
        log.warning(
            "Shadow invalidation CRITICAL diff detected: %d diffs (session=%s)",
            len(invalidation_result.critical_diffs),
            session_id,
        )

    return str(out_path)


def _diff_entry_dict(entry: ShadowDiffEntry) -> dict:
    return {
        "field": entry.field_name,
        "legacy": _serialize_value(entry.legacy_value),
        "incremental": _serialize_value(entry.incremental_value),
        "critical": entry.is_critical,
    }


def _serialize_value(val: object) -> object:
    """Best-effort JSON-friendly serialization."""
    if isinstance(val, (str, int, float, bool, type(None))):
        return val
    if isinstance(val, (list, tuple)):
        return list(val)
    return str(val)

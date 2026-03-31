"""Incremental Decision Compiler (Step 05).

Rebuilds only dirty obligation blocks and reuses cached blocks for
clean obligations.  Falls back to the full legacy compiler when
projection data is missing or inconsistent.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

from egtsr_runtime.compiler.cache_models import compute_render_hash
from egtsr_runtime.compiler.decision_compiler import DecisionCapsuleCompiler
from egtsr_runtime.compiler.decision_models import (
    DecisionCapsuleV0,
    DecisionCompilerInput,
    ObligationBlock,
)
from egtsr_runtime.compiler.materializer import materialize_for_obligations
from egtsr_runtime.compiler.next_checks import derive_next_check
from egtsr_runtime.compiler.ordering import sort_obligations
from egtsr_runtime.compiler.pools import (
    build_obligation_block,
    has_recent_failed_family,
    has_unresolved_stale_ticket,
)
from egtsr_runtime.compiler.renderer import render_capsule
from egtsr_runtime.compiler.token_estimator import estimate_tokens, trim_to_budget
from egtsr_runtime.enums import (
    AssertionStatus,
    InvalidationStatus,
    ObligationStatus,
)

log = logging.getLogger(__name__)

# If more than this fraction of obligations are dirty, fall back to full compile
_DIRTY_RATIO_THRESHOLD = 0.8


@dataclass(slots=True)
class IncrementalCompileResult:
    capsule: DecisionCapsuleV0
    used_incremental: bool
    dirty_count: int = 0
    rebuilt_count: int = 0
    cache_hit_count: int = 0
    fallback_reason: str | None = None


class IncrementalDecisionCompiler:
    """Compile decision capsule incrementally via obligation frontier cache."""

    def __init__(self, uow, token_budget: int) -> None:
        self._uow = uow
        self._token_budget = token_budget
        self._legacy = DecisionCapsuleCompiler()

    def compile(self, session_id: str) -> IncrementalCompileResult:
        """Run incremental compile, falling back to full on error."""
        try:
            return self._try_incremental(session_id)
        except Exception as exc:
            log.warning("Incremental compile failed, falling back to full: %s", exc)
            capsule = self._full_compile(session_id)
            return IncrementalCompileResult(
                capsule=capsule,
                used_incremental=False,
                fallback_reason=f"exception: {exc}",
            )

    # ------------------------------------------------------------------
    # Incremental path
    # ------------------------------------------------------------------

    def _try_incremental(self, session_id: str) -> IncrementalCompileResult:
        # 1. Session frontier
        sf = self._uow.session_frontier.get(session_id)

        # 2. All open obligations (for sorting / header — single indexed query)
        open_obligations = self._uow.obligations.list_open(session_id)
        if not open_obligations:
            return self._empty_capsule_result(session_id)

        sorted_obligations = sort_obligations(open_obligations)
        open_obligation_ids = [o.id for o in sorted_obligations]

        # 3. Dirty obligation IDs from frontier
        dirty_id_set = set(self._uow.obligation_frontier.list_dirty_ids(session_id))
        dirty_ids = [oid for oid in open_obligation_ids if oid in dirty_id_set]
        clean_ids = [oid for oid in open_obligation_ids if oid not in dirty_id_set]

        # Fallback: projection rows missing for any open obligation
        frontier_rows = {
            r.obligation_id: r
            for r in self._uow.obligation_frontier.list_for_session(session_id)
        }
        missing = [oid for oid in open_obligation_ids if oid not in frontier_rows]
        if missing:
            log.info("Missing frontier rows for %d obligations, full compile", len(missing))
            capsule = self._full_compile(session_id)
            return IncrementalCompileResult(
                capsule=capsule,
                used_incremental=False,
                fallback_reason=f"missing_frontier_rows:{len(missing)}",
            )

        # Fallback: too many dirty (only after first compile — initial compile is always incremental)
        has_prior_compile = sf is not None and sf.last_compiled_capsule_id is not None
        if (
            has_prior_compile
            and open_obligation_ids
            and len(dirty_ids) > len(open_obligation_ids) * _DIRTY_RATIO_THRESHOLD
        ):
            capsule = self._full_compile(session_id)
            return IncrementalCompileResult(
                capsule=capsule,
                used_incremental=False,
                dirty_count=len(dirty_ids),
                fallback_reason="dirty_ratio_exceeded",
            )

        # 4. Cache hash validation: clean obligations with no render cache
        #    are promoted to dirty (handles projection rebuild, first compile,
        #    or any case where dirty flag was missed).
        stale_clean = [
            oid for oid in clean_ids
            if frontier_rows[oid].render_hash is None
        ]
        if stale_clean:
            log.info(
                "Promoting %d clean obligations to dirty (no render cache)",
                len(stale_clean),
            )
            dirty_id_set.update(stale_clean)
            dirty_ids = [oid for oid in open_obligation_ids if oid in dirty_id_set]
            clean_ids = [oid for oid in open_obligation_ids if oid not in dirty_id_set]

        # 5. Rebuild dirty blocks
        now = datetime.now(timezone.utc).isoformat()
        dirty_blocks: dict[str, ObligationBlock] = {}

        if dirty_ids:
            mat = materialize_for_obligations(self._uow, session_id, dirty_ids)
            assertions_by_obl: dict[str, list] = {}
            for a in mat.assertions:
                if a.obligation_id:
                    assertions_by_obl.setdefault(a.obligation_id, []).append(a)

            for obl in sorted_obligations:
                if obl.id not in dirty_id_set:
                    continue
                obl_assertions = assertions_by_obl.get(obl.id, [])
                block = build_obligation_block(
                    obligation=obl,
                    obligation_assertions=obl_assertions,
                    evidence=mat.evidence,
                    invalidation_tickets=mat.invalidation_tickets,
                    attempt_families=mat.attempt_families,
                )
                # Compute next_check
                next_check = derive_next_check(
                    obligation=obl,
                    positive=block.positive_items,
                    negative=block.negative_items,
                    uncertainty=block.uncertainty_items,
                    has_recent_failed_family=has_recent_failed_family(
                        obl.id, mat.attempt_families
                    ),
                    has_unresolved_stale_ticket=has_unresolved_stale_ticket(
                        obl.id, obl_assertions, mat.invalidation_tickets
                    ),
                )
                block.suggested_next_check = next_check
                dirty_blocks[obl.id] = block

                # Update frontier cache
                render_hash = compute_render_hash(
                    obligation_id=obl.id,
                    obligation_status=obl.status.value,
                    obligation_priority=obl.priority,
                    assertion_summaries=[
                        (a.id, a.status.value, a.updated_at or "")
                        for a in obl_assertions
                    ],
                    evidence_summaries=[
                        (e.id, e.polarity, e.path or e.scope_ref)
                        for e in mat.evidence
                        if e.id in {eid for a in obl_assertions for eid in a.evidence_ids}
                    ],
                    live_ticket_ids=[t.id for t in mat.invalidation_tickets],
                    failed_family_summaries=[
                        (f.id, f.fail_count)
                        for f in mat.attempt_families
                        if f.obligation_id == obl.id
                    ],
                    token_budget=self._token_budget,
                )
                self._uow.obligation_frontier.update_render_cache(
                    obligation_id=obl.id,
                    rendered_positive_json=json.dumps(block.positive_items),
                    rendered_negative_json=json.dumps(block.negative_items),
                    rendered_uncertainty_json=json.dumps(block.uncertainty_items),
                    suggested_next_check=next_check,
                    render_hash=render_hash,
                    token_estimate=estimate_tokens(
                        "\n".join(block.positive_items + block.negative_items + block.uncertainty_items)
                    ),
                    updated_at=now,
                )

            # Mark dirty obligations clean
            self._uow.obligation_frontier.bulk_mark_clean(dirty_ids, now)

        # 6. Assemble all blocks (dirty rebuilt + clean from cache)
        obligation_blocks: list[ObligationBlock] = []
        next_checks: list[str] = []

        for obl in sorted_obligations:
            if obl.id in dirty_blocks:
                block = dirty_blocks[obl.id]
            else:
                # Reconstruct from cache
                fr = frontier_rows[obl.id]
                block = ObligationBlock(
                    obligation_id=obl.id,
                    priority=obl.priority,
                    title=obl.statement,
                    state=obl.status.value,
                    positive_items=json.loads(fr.rendered_positive_json),
                    negative_items=json.loads(fr.rendered_negative_json),
                    uncertainty_items=json.loads(fr.rendered_uncertainty_json),
                    suggested_next_check=fr.suggested_next_check or "",
                )
            obligation_blocks.append(block)
            next_checks.append(f"{obl.id}: {block.suggested_next_check}")

        # 7. Build capsule-level data (warnings, audit_inputs)
        live_tickets = self._uow.invalidations.list_live_for_session(session_id)

        warnings = self._build_warnings(sorted_obligations, live_tickets)
        stale_evidence_ids_seen = sorted(
            t.subject_id for t in live_tickets if t.subject_type == "evidence"
        )
        unsupported_confirmed = self._compute_unsupported_confirmed(session_id)

        header_obligations = [o.id for o in sorted_obligations]

        capsule = DecisionCapsuleV0(
            header_obligations=header_obligations,
            warnings=warnings,
            obligation_blocks=obligation_blocks,
            next_checks=next_checks,
            audit_inputs={
                "session_id": session_id,
                "budget": self._token_budget,
                "open_obligation_ids": header_obligations,
                "rendered_obligation_ids": [b.obligation_id for b in obligation_blocks],
                "stale_evidence_ids_seen": stale_evidence_ids_seen,
                "unsupported_confirmed_assertion_ids": unsupported_confirmed,
                "live_stale_ticket_ids": [
                    t.id for t in sorted(live_tickets, key=lambda t: (t.created_at or "", t.id))
                ],
                "reopened_obligation_ids": [
                    o.id for o in sorted_obligations
                    if o.status == ObligationStatus.REOPENED
                ],
            },
        )
        capsule.rendered_text = render_capsule(capsule)
        capsule.token_estimate = estimate_tokens(capsule.rendered_text)

        if capsule.token_estimate > self._token_budget:
            capsule = trim_to_budget(capsule, self._token_budget)

        capsule.rendered_text = render_capsule(capsule)
        capsule.token_estimate = estimate_tokens(capsule.rendered_text)

        return IncrementalCompileResult(
            capsule=capsule,
            used_incremental=True,
            dirty_count=len(dirty_ids),
            rebuilt_count=len(dirty_blocks),
            cache_hit_count=len(clean_ids),
        )

    # ------------------------------------------------------------------
    # Full compile fallback
    # ------------------------------------------------------------------

    def _full_compile(self, session_id: str) -> DecisionCapsuleV0:
        compiler_input = DecisionCompilerInput(
            session_id=session_id,
            token_budget=self._token_budget,
            open_obligations=self._uow.obligations.list_open(session_id),
            evidence=self._uow.evidence.list_for_session(session_id),
            assertions=self._uow.assertions.list_for_session(session_id),
            invalidation_tickets=self._uow.invalidations.list_for_session(session_id),
            attempt_families=self._uow.attempt_families.list_for_session(session_id),
        )
        return self._legacy.compile(compiler_input)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_warnings(obligations: list, live_tickets: list) -> list[str]:
        warnings: list[str] = []
        for obligation in obligations:
            if obligation.status == ObligationStatus.REOPENED:
                warnings.append(f"Reopened obligation: {obligation.id}")
        for ticket in sorted(live_tickets, key=lambda t: (t.created_at or "", t.id)):
            warnings.append(f"Live stale ticket: {ticket.subject_type}:{ticket.subject_id}")
        return warnings

    def _compute_unsupported_confirmed(self, session_id: str) -> list[str]:
        """Compute unsupported confirmed assertion IDs efficiently.

        Uses a lightweight query fetching only id/obligation_id/status
        rather than loading full assertion objects for the entire session.
        """
        conn = self._uow._require_connection()
        rows = conn.execute(
            """SELECT id, obligation_id, status FROM assertions
               WHERE session_id = ? AND status IN (?, ?) AND obligation_id IS NOT NULL""",
            (session_id, AssertionStatus.SUPPORTED.value, AssertionStatus.CONFIRMED.value),
        ).fetchall()

        by_obligation: dict[str, list] = {}
        for row in rows:
            by_obligation.setdefault(row["obligation_id"], []).append(row)

        unsupported: list[str] = []
        for obl_rows in by_obligation.values():
            if any(r["status"] == AssertionStatus.SUPPORTED.value for r in obl_rows):
                continue
            unsupported.extend(
                r["id"] for r in obl_rows if r["status"] == AssertionStatus.CONFIRMED.value
            )
        return sorted(unsupported)

    @staticmethod
    def _empty_capsule_result(session_id: str) -> IncrementalCompileResult:
        capsule = DecisionCapsuleV0(
            header_obligations=[],
            warnings=[],
            obligation_blocks=[],
            next_checks=[],
            audit_inputs={
                "session_id": session_id,
                "budget": 0,
                "open_obligation_ids": [],
                "rendered_obligation_ids": [],
                "stale_evidence_ids_seen": [],
                "unsupported_confirmed_assertion_ids": [],
                "live_stale_ticket_ids": [],
                "reopened_obligation_ids": [],
            },
        )
        capsule.rendered_text = render_capsule(capsule)
        capsule.token_estimate = estimate_tokens(capsule.rendered_text)
        return IncrementalCompileResult(
            capsule=capsule,
            used_incremental=True,
            dirty_count=0,
            rebuilt_count=0,
            cache_hit_count=0,
        )

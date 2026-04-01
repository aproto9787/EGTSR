from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

from egtsr_runtime.compiler import (
    CapsuleAuditEngine,
    CapsuleAuditReport,
    DecisionCapsuleCompiler,
    DecisionCapsuleV0,
    DecisionCompilerInput,
    IncrementalDecisionCompiler,
    PromptIntentClassifier,
    PromptRiskFlags,
    classify_prompt_intent_v2,
)
from egtsr_runtime.enums import VerifyPhase
from egtsr_runtime.hooks.envelopes import HookEnvelope
from egtsr_runtime.hooks.responses import build_allow_response, build_block_response
from egtsr_runtime.models import Capsule, Event
from egtsr_runtime.paths import ensure_runtime_dirs
from egtsr_runtime.services.freshness_gate import FreshnessGateService
from egtsr_runtime.services.raw_archive import archive_raw_event
from egtsr_runtime.services.resume_gate import ResumeGateService, ResumeGateState
from egtsr_runtime.services.snapshot_writer import SnapshotWriter


@dataclass(slots=True)
class PromptGateResult:
    allowed: bool
    response: dict
    audit_report: CapsuleAuditReport | None
    intent: str  # v1-compatible string (from PromptRiskFlags.raw_intent)
    risk_flags: PromptRiskFlags | None
    capsule: DecisionCapsuleV0 | None


class UserPromptSubmitService:
    def __init__(self, uow, config, raw_events_dir: str):
        self._uow = uow
        self._config = config
        self._raw_events_dir = raw_events_dir
        self._compiler = DecisionCapsuleCompiler()
        self._audit_engine = CapsuleAuditEngine()
        self._intent_classifier = PromptIntentClassifier()
        self._paths = ensure_runtime_dirs(config.repo_root)
        self._resume_gate = ResumeGateService(uow)
        self._snapshot_writer = SnapshotWriter(self._paths)

    def handle(self, envelope: HookEnvelope) -> PromptGateResult:
        """Handle UserPromptSubmit hook event.

        Fail-closed: ANY unhandled exception results in a block response.
        user_prompt_submit never falls back to allow on error.
        """
        now = datetime.now(timezone.utc).isoformat()

        # --- Phase 1: archive + classify (fail-closed on error) ---
        try:
            archive_path = archive_raw_event(self._raw_events_dir, envelope)
        except Exception as exc:
            return self._fail_closed_result(
                envelope, now, "runtime_state_corrupt", f"archive failed: {exc}"
            )

        try:
            risk_flags = classify_prompt_intent_v2(envelope.prompt or "")
            intent = risk_flags.raw_intent
        except Exception as exc:
            return self._fail_closed_result(
                envelope, now, "gate_evaluation_failed", f"intent classifier failed: {exc}"
            )

        # --- Phase 2: resume gate (fail-closed on error) ---
        try:
            gate = self._load_or_evaluate_gate(envelope)
        except Exception as exc:
            return self._fail_closed_result(
                envelope, now, "freshness_state_unavailable", f"gate evaluation failed: {exc}"
            )

        if self._resume_gate.should_block_prompt(gate, risk_flags):
            response = build_block_response(
                reason=gate.reason or "Resume gate active",
                additional_context=self._gate_context(
                    intent=intent,
                    gate=gate,
                    archive_path=archive_path,
                ),
            )
            self._log_event(
                session_id=envelope.session_id,
                created_at=now,
                event_type="user_prompt_submit.handled",
                payload={
                    "hook_event_name": envelope.hook_event_name,
                    "source": envelope.source,
                    "intent": intent,
                    "allowed": False,
                    "safe_resume": envelope.source in {"resume", "compact"},
                    "resume_gate_blocked": True,
                    "required_rechecks": gate.required_rechecks,
                    "compiler_status": "skipped",
                    "raw_archive_path": archive_path,
                },
            )
            self._uow.commit()
            return PromptGateResult(
                allowed=False,
                response=response,
                audit_report=None,
                intent=intent,
                risk_flags=risk_flags,
                capsule=None,
            )

        # --- Phase 2.5: freshness gate (fail-closed on error) ---
        try:
            freshness_gate = FreshnessGateService(self._uow, self._config.repo_root)
            freshness_diff = freshness_gate.check_freshness(envelope.session_id)
        except Exception as exc:
            return self._fail_closed_result(
                envelope, now, "freshness_check_failed", f"freshness gate error: {exc}"
            )

        if freshness_diff.has_mismatch and self._is_write_risk(risk_flags):
            mismatch_desc = FreshnessGateService.describe_mismatch(freshness_diff)
            response = build_block_response(
                reason=f"Freshness mismatch: {mismatch_desc}",
                additional_context=self._freshness_block_context(
                    intent=intent,
                    mismatch=mismatch_desc,
                    archive_path=archive_path,
                ),
            )
            self._log_event(
                session_id=envelope.session_id,
                created_at=now,
                event_type="user_prompt_submit.handled",
                payload={
                    "hook_event_name": envelope.hook_event_name,
                    "source": envelope.source,
                    "intent": intent,
                    "allowed": False,
                    "freshness_mismatch": True,
                    "freshness_detail": mismatch_desc,
                    "compiler_status": "skipped",
                    "raw_archive_path": archive_path,
                },
            )
            self._uow.commit()
            return PromptGateResult(
                allowed=False,
                response=response,
                audit_report=None,
                intent=intent,
                risk_flags=risk_flags,
                capsule=None,
            )

        # --- Phase 3: compile + audit (fail-closed on error) ---
        try:
            compiled_capsule = self._compile_capsule(envelope.session_id)
            audit_report = self._audit_engine.audit(compiled_capsule)
            stored_capsule_id = self._store_capsule(
                envelope=envelope,
                capsule=compiled_capsule,
                audit_report=audit_report,
                created_at=now,
            )
        except Exception as exc:
            response = build_block_response(
                reason=f"decision_capsule_unavailable: {exc}",
                additional_context=f"intent={intent}; raw_archive={archive_path}",
            )
            self._log_event(
                session_id=envelope.session_id,
                created_at=now,
                event_type="user_prompt_submit.handled",
                payload={
                    "hook_event_name": envelope.hook_event_name,
                    "source": envelope.source,
                    "intent": intent,
                    "allowed": False,
                    "safe_resume": envelope.source in {"resume", "compact"},
                    "compiler_status": "crashed",
                    "error": str(exc),
                    "raw_archive_path": archive_path,
                },
            )
            self._uow.commit()
            return PromptGateResult(
                allowed=False,
                response=response,
                audit_report=None,
                intent=intent,
                risk_flags=risk_flags,
                capsule=None,
            )

        if audit_report.passed:
            response = build_allow_response(
                envelope.hook_event_name,
                additional_context=self._allow_context(
                    intent=intent,
                    capsule=compiled_capsule,
                    audit_report=audit_report,
                    capsule_id=stored_capsule_id,
                    archive_path=archive_path,
                ),
            )
            allowed = True
        else:
            response = build_block_response(
                reason="; ".join(audit_report.hard_fail_reasons),
                additional_context=self._block_context(
                    intent=intent,
                    archive_path=archive_path,
                    capsule_id=stored_capsule_id,
                ),
            )
            allowed = False

        self._log_event(
            session_id=envelope.session_id,
            created_at=now,
            event_type="user_prompt_submit.handled",
            payload={
                "hook_event_name": envelope.hook_event_name,
                "source": envelope.source,
                "intent": intent,
                "allowed": allowed,
                "safe_resume": envelope.source in {"resume", "compact"},
                "resume_gate_blocked": False,
                "compiler_status": "ok",
                "audit_pass": audit_report.passed,
                "capsule_id": stored_capsule_id,
                "raw_archive_path": archive_path,
            },
        )
        self._uow.commit()
        return PromptGateResult(
            allowed=allowed,
            response=response,
            audit_report=audit_report,
            intent=intent,
            risk_flags=risk_flags,
            capsule=compiled_capsule,
        )

    def _fail_closed_result(
        self,
        envelope: HookEnvelope,
        now: str,
        block_reason: str,
        detail: str,
    ) -> PromptGateResult:
        """Return a fail-closed block result for any early-stage exception."""
        response = build_block_response(
            reason=f"{block_reason}: {detail}",
            additional_context=f"egtsr_fail_closed: {block_reason}",
        )
        try:
            self._log_event(
                session_id=envelope.session_id,
                created_at=now,
                event_type="user_prompt_submit.fail_closed",
                payload={
                    "hook_event_name": envelope.hook_event_name,
                    "source": envelope.source,
                    "block_reason": block_reason,
                    "detail": detail,
                },
            )
            self._uow.commit()
        except Exception:
            pass  # logging failure must not mask the block
        return PromptGateResult(
            allowed=False,
            response=response,
            audit_report=None,
            intent="ambiguous",
            risk_flags=None,
            capsule=None,
        )

    def _compile_capsule(self, session_id: str) -> DecisionCapsuleV0:
        """Compile a decision capsule using incremental, shadow, or legacy path."""
        from egtsr_runtime.config import is_shadow_mode

        if is_shadow_mode(self._config):
            return self._compile_shadow(session_id)
        if self._config.enable_incremental_compile:
            inc = IncrementalDecisionCompiler(self._uow, self._config.max_decision_tokens)
            result = inc.compile(session_id)
            return result.capsule
        compiler_input = self._build_compiler_input(session_id)
        return self._compiler.compile(compiler_input)

    def _compile_shadow(self, session_id: str) -> DecisionCapsuleV0:
        """Dual-run compile: legacy + incremental, diff, use legacy result."""
        from egtsr_runtime.compat.shadow_runner import (
            ShadowCompileRunner,
            write_shadow_diff_report,
        )

        runner = ShadowCompileRunner(self._uow, self._config)
        shadow_result = runner.compile(session_id)

        write_shadow_diff_report(
            self._paths.reports_dir,
            hook_name="user_prompt_submit",
            session_id=session_id,
            compile_result=shadow_result,
        )

        # Always use legacy capsule for safety
        return shadow_result.legacy_capsule

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

    def _store_capsule(self, envelope, capsule, audit_report, created_at: str) -> str:
        capsule_id = uuid.uuid4().hex
        self._uow.capsules.create(
            Capsule(
                id=capsule_id,
                session_id=envelope.session_id,
                phase=VerifyPhase.DECISION,
                frontier_hash=self._frontier_hash(envelope, capsule),
                content=capsule.rendered_text,
                token_count=capsule.token_estimate,
                audit_pass=audit_report.passed,
                audit_report=asdict(audit_report),
                created_at=created_at,
            )
        )
        return capsule_id

    def _frontier_hash(self, envelope, capsule) -> str:
        payload = {
            "session_id": envelope.session_id,
            "source": envelope.source,
            "prompt": envelope.prompt or "",
            "open_obligation_ids": capsule.audit_inputs.get("open_obligation_ids", []),
            "rendered_obligation_ids": capsule.audit_inputs.get("rendered_obligation_ids", []),
            "stale_evidence_ids_seen": capsule.audit_inputs.get("stale_evidence_ids_seen", []),
            "unsupported_confirmed_assertion_ids": capsule.audit_inputs.get(
                "unsupported_confirmed_assertion_ids", []
            ),
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()

    def _log_event(self, session_id: str, created_at: str, event_type: str, payload: dict) -> None:
        self._uow.events.create(
            Event(
                id=uuid.uuid4().hex,
                session_id=session_id,
                event_type=event_type,
                payload=payload,
                created_at=created_at,
            )
        )

    @staticmethod
    def _allow_context(intent: str, capsule, audit_report, capsule_id: str, archive_path: str) -> str:
        return (
            f"intent={intent}; "
            f"audit_pass={str(audit_report.passed).lower()}; "
            f"capsule_id={capsule_id}; "
            f"token_estimate={capsule.token_estimate}; "
            f"raw_archive={archive_path}\n"
            f"{capsule.rendered_text}"
        )

    @staticmethod
    def _block_context(intent: str, archive_path: str, capsule_id: str) -> str:
        return f"intent={intent}; capsule_id={capsule_id}; raw_archive={archive_path}"

    def _load_or_evaluate_gate(self, envelope: HookEnvelope) -> ResumeGateState:
        try:
            stored_gate = self._uow.resume_gate_repo.get(envelope.session_id)
        except Exception as exc:
            stored_gate = self._db_corruption_gate(
                envelope.session_id,
                f"resume_gate_repo read failed: {exc}",
            )

        try:
            repo_state = self._uow.repo_state.get(envelope.session_id)
        except Exception:
            return self._prefer_blocked_gate(
                stored_gate,
                self._db_corruption_gate(envelope.session_id),
            )

        evaluated_gate = self._resume_gate.evaluate(
            session_id=envelope.session_id,
            source=envelope.source,
            repo_dirty=bool(repo_state and repo_state.dirty),
        )
        return self._prefer_blocked_gate(stored_gate, evaluated_gate)

    @staticmethod
    def _prefer_blocked_gate(
        stored_gate: ResumeGateState | None,
        evaluated_gate: ResumeGateState,
    ) -> ResumeGateState:
        if stored_gate is None:
            return evaluated_gate
        if stored_gate.edit_blocked and not evaluated_gate.edit_blocked:
            return stored_gate
        if stored_gate.edit_blocked and evaluated_gate.edit_blocked:
            merged_rechecks: list[str] = []
            for item in [*stored_gate.required_rechecks, *evaluated_gate.required_rechecks]:
                if item not in merged_rechecks:
                    merged_rechecks.append(item)
            merged_reason = stored_gate.reason or evaluated_gate.reason
            if stored_gate.reason and evaluated_gate.reason and stored_gate.reason != evaluated_gate.reason:
                merged_reason = f"{stored_gate.reason}; {evaluated_gate.reason}"
            return ResumeGateState(
                session_id=evaluated_gate.session_id or stored_gate.session_id,
                edit_blocked=True,
                reason=merged_reason,
                required_rechecks=merged_rechecks,
                updated_at=evaluated_gate.updated_at or stored_gate.updated_at,
            )
        return evaluated_gate

    @staticmethod
    def _db_corruption_gate(session_id: str, detail: str = "db_health_check_failed") -> ResumeGateState:
        return ResumeGateState(
            session_id=session_id,
            edit_blocked=True,
            reason=f"Resume gate active: {detail}",
            required_rechecks=["db_health_check_failed"],
            updated_at=datetime.now(timezone.utc).isoformat(),
        )

    @staticmethod
    def _is_write_risk(risk_flags: PromptRiskFlags | None) -> bool:
        """write-risk prompt인지 판정."""
        if risk_flags is None:
            return True  # fail-closed: unknown → write-risk
        return (
            risk_flags.requests_write
            or risk_flags.requests_repo_mutation
            or risk_flags.ambiguous
        )

    @staticmethod
    def _freshness_block_context(
        intent: str, mismatch: str, archive_path: str
    ) -> str:
        return (
            f"intent={intent}; "
            f"freshness_mismatch={mismatch}; "
            f"raw_archive={archive_path}"
        )

    @staticmethod
    def _gate_context(intent: str, gate: ResumeGateState, archive_path: str) -> str:
        return (
            f"intent={intent}; "
            f"required_rechecks={','.join(gate.required_rechecks) or 'none'}; "
            f"raw_archive={archive_path}"
        )

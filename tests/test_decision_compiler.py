from __future__ import annotations

import json
import unittest
from pathlib import Path

from egtsr_runtime.compiler import DecisionCapsuleCompiler, DecisionCompilerInput
from egtsr_runtime.enums import AssertionStatus, InvalidationStatus, ObligationStatus
from egtsr_runtime.models import Assertion, AttemptFamily, Evidence, InvalidationTicket, Obligation

FIXTURE_DIR = Path("tests/fixtures/compiler")


class TestDecisionCompiler(unittest.TestCase):
    def setUp(self) -> None:
        self.compiler = DecisionCapsuleCompiler()

    def test_reopened_regression_at_top(self):
        """Reopened obligation always appears first in header and blocks"""
        capsule = self.compiler.compile(_load_fixture("reopened_regression_priority.json"))

        self.assertEqual(capsule.header_obligations[0], "obl-reopened")
        self.assertEqual(capsule.obligation_blocks[0].obligation_id, "obl-reopened")

    def test_open_obligation_100_inclusion(self):
        """All open obligations appear in header_obligations"""
        data = _load_fixture("reopened_regression_priority.json")
        capsule = self.compiler.compile(data)

        self.assertCountEqual(
            capsule.header_obligations,
            [obligation.id for obligation in data.open_obligations],
        )

    def test_stale_evidence_excluded(self):
        """Stale assertions/evidence not in positive/negative/uncertainty items"""
        capsule = self.compiler.compile(_load_fixture("stale_evidence_excluded.json"))
        block = capsule.obligation_blocks[0]
        body = "\n".join(block.positive_items + block.negative_items + block.uncertainty_items)

        self.assertIn("live evidence excerpt", body)
        self.assertNotIn("stale evidence excerpt", body)
        self.assertNotIn("Stale assertion", body)

    def test_negative_evidence_placeholder(self):
        """Every obligation has at least one negative item (placeholder if none)"""
        capsule = self.compiler.compile(_load_fixture("negative_evidence_required.json"))

        for block in capsule.obligation_blocks:
            self.assertTrue(block.negative_items)
            self.assertIn("[No negative evidence — verify before proceeding]", block.negative_items)

    def test_no_live_evidence_read_required(self):
        """Obligation with no live evidence gets READ_REQUIRED next-check"""
        capsule = self.compiler.compile(_load_fixture("no_live_evidence_read_required.json"))
        block = capsule.obligation_blocks[0]

        self.assertEqual(block.suggested_next_check, "READ_REQUIRED")
        self.assertIn("[No live evidence — READ REQUIRED]", block.uncertainty_items)

    def test_tight_budget_no_header_omission(self):
        """Even with tight budget, all obligations in header"""
        data = _load_fixture("tight_budget_no_omission.json")
        capsule = self.compiler.compile(data)

        self.assertCountEqual(
            capsule.header_obligations,
            [obligation.id for obligation in data.open_obligations],
        )
        self.assertEqual(len(capsule.obligation_blocks), len(data.open_obligations))

    def test_failed_family_investigate_alt_path(self):
        """Recent failed family -> INVESTIGATE_ALT_PATH next-check"""
        capsule = self.compiler.compile(_load_fixture("recent_failed_family_alt_path.json"))
        block = capsule.obligation_blocks[0]

        self.assertEqual(block.suggested_next_check, "INVESTIGATE_ALT_PATH")
        self.assertTrue(any("Three failed attempts" in item for item in block.negative_items))

    def test_unsupported_confirmed_assertion_excluded(self):
        """Unsupported confirmed assertion is excluded from rendered body"""
        capsule = self.compiler.compile(_load_fixture("unsupported_confirmed_assertion_blocked.json"))
        block = capsule.obligation_blocks[0]
        body = "\n".join(block.positive_items + block.negative_items + block.uncertainty_items)

        self.assertNotIn("Unsupported confirmed assertion", body)
        self.assertNotIn("unsupported confirmed excerpt", body)
        self.assertEqual(block.positive_items, [])

    def test_rendered_text_not_empty(self):
        """Compiler produces non-empty rendered_text"""
        capsule = self.compiler.compile(_load_fixture("negative_evidence_required.json"))

        self.assertTrue(capsule.rendered_text.strip())
        self.assertIn("--- DECISION CAPSULE ---", capsule.rendered_text)

    def test_deterministic_output(self):
        """Same input produces same output"""
        data = _load_fixture("stale_evidence_excluded.json")

        first = self.compiler.compile(data)
        second = self.compiler.compile(_load_fixture("stale_evidence_excluded.json"))

        self.assertEqual(first, second)



def _load_fixture(name: str) -> DecisionCompilerInput:
    payload = json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))
    session_id = payload["session_id"]
    return DecisionCompilerInput(
        session_id=session_id,
        token_budget=payload["token_budget"],
        open_obligations=[_make_obligation(item) for item in payload.get("obligations", [])],
        evidence=[_make_evidence(item) for item in payload.get("evidence", [])],
        assertions=[_make_assertion(item) for item in payload.get("assertions", [])],
        invalidation_tickets=[
            _make_invalidation_ticket(item) for item in payload.get("invalidation_tickets", [])
        ],
        attempt_families=[_make_attempt_family(item) for item in payload.get("attempt_families", [])],
    )



def _make_obligation(item: dict) -> Obligation:
    return Obligation(
        id=item["id"],
        session_id=item["session_id"],
        source=item["source"],
        statement=item["statement"],
        priority=item.get("priority", 50),
        status=ObligationStatus(item.get("status", "open")),
        acceptance_check=item.get("acceptance_check"),
        metadata=item.get("metadata", {}),
        created_at=item.get("created_at", ""),
        updated_at=item.get("updated_at", ""),
    )



def _make_evidence(item: dict) -> Evidence:
    return Evidence(
        id=item["id"],
        session_id=item["session_id"],
        kind=item["kind"],
        source_tool=item["source_tool"],
        path=item.get("path"),
        scope_kind=item.get("scope_kind"),
        scope_ref=item.get("scope_ref"),
        file_hash=item.get("file_hash"),
        polarity=item.get("polarity", "positive"),
        excerpt=item.get("excerpt"),
        metadata=item.get("metadata", {}),
        created_at=item.get("created_at", ""),
    )



def _make_assertion(item: dict) -> Assertion:
    return Assertion(
        id=item["id"],
        session_id=item["session_id"],
        obligation_id=item.get("obligation_id"),
        statement=item["statement"],
        scope_kind=item.get("scope_kind"),
        scope_ref=item.get("scope_ref"),
        status=AssertionStatus(item.get("status", "speculative")),
        confidence=item.get("confidence", 0.5),
        evidence_ids=item.get("evidence_ids", []),
        metadata=item.get("metadata", {}),
        created_at=item.get("created_at", ""),
        updated_at=item.get("updated_at", ""),
    )



def _make_invalidation_ticket(item: dict) -> InvalidationTicket:
    return InvalidationTicket(
        id=item["id"],
        session_id=item["session_id"],
        subject_type=item["subject_type"],
        subject_id=item["subject_id"],
        trigger_kind=item["trigger_kind"],
        trigger_ref=item.get("trigger_ref"),
        status=InvalidationStatus(item.get("status", "live")),
        metadata=item.get("metadata", {}),
        created_at=item.get("created_at", ""),
        updated_at=item.get("updated_at", ""),
    )



def _make_attempt_family(item: dict) -> AttemptFamily:
    return AttemptFamily(
        id=item["id"],
        session_id=item["session_id"],
        obligation_id=item.get("obligation_id"),
        signature=item["signature"],
        touched_scope=item.get("touched_scope", []),
        fail_count=item.get("fail_count", 1),
        last_outcome=item.get("last_outcome", ""),
        summary=item.get("summary"),
        metadata=item.get("metadata", {}),
        created_at=item.get("created_at", ""),
        updated_at=item.get("updated_at", ""),
    )


if __name__ == "__main__":
    unittest.main()

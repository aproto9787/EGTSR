from __future__ import annotations

import json
import unittest
from dataclasses import asdict

from egtsr_runtime.compiler import CapsuleAuditEngine, DecisionCapsuleV0, ObligationBlock


class CapsuleAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = CapsuleAuditEngine()

    def test_audit_passes_when_capsule_is_clean(self) -> None:
        capsule = self._capsule(
            open_ids=["obl-1"],
            rendered_ids=["obl-1"],
        )

        report = self.engine.audit(capsule)

        self.assertTrue(report.passed)
        self.assertEqual(report.hard_fail_reasons, [])
        self.assertEqual(report.rendered_obligation_ids, ["obl-1"])

    def test_audit_fails_on_omission(self) -> None:
        capsule = self._capsule(
            open_ids=["obl-1", "obl-2"],
            rendered_ids=["obl-1"],
        )

        report = self.engine.audit(capsule)

        self.assertFalse(report.passed)
        self.assertIn("Omission: missing rendered obligations: obl-2", report.hard_fail_reasons)

    def test_audit_fails_on_stale_evidence_leak(self) -> None:
        capsule = self._capsule(
            open_ids=["obl-1"],
            rendered_ids=["obl-1"],
            stale_ids=["ev-stale"],
        )

        report = self.engine.audit(capsule)

        self.assertFalse(report.passed)
        self.assertIn("Stale evidence leak: ev-stale", report.hard_fail_reasons)

    def test_audit_fails_on_unsupported_confirmed_assertion(self) -> None:
        capsule = self._capsule(
            open_ids=["obl-1"],
            rendered_ids=["obl-1"],
            unsupported_ids=["as-unsupported"],
        )

        report = self.engine.audit(capsule)

        self.assertFalse(report.passed)
        self.assertIn(
            "Unsupported confirmed assertions: as-unsupported",
            report.hard_fail_reasons,
        )

    def test_audit_report_is_json_serializable_dict(self) -> None:
        capsule = self._capsule(
            open_ids=["obl-1"],
            rendered_ids=["obl-1"],
        )

        report = self.engine.audit(capsule)
        payload = asdict(report)

        encoded = json.dumps(payload)

        self.assertIn('"passed": true', encoded)
        self.assertEqual(payload["budget"], 900)

    def test_hard_fail_reasons_list_populated_correctly(self) -> None:
        capsule = self._capsule(
            open_ids=["obl-1", "obl-2"],
            rendered_ids=["obl-1"],
            stale_ids=["ev-stale"],
            unsupported_ids=["as-unsupported"],
        )

        report = self.engine.audit(capsule)

        self.assertEqual(len(report.hard_fail_reasons), 3)
        self.assertTrue(any(reason.startswith("Omission:") for reason in report.hard_fail_reasons))
        self.assertTrue(any(reason.startswith("Stale evidence leak:") for reason in report.hard_fail_reasons))
        self.assertTrue(
            any(reason.startswith("Unsupported confirmed assertions:") for reason in report.hard_fail_reasons)
        )

    @staticmethod
    def _capsule(
        *,
        open_ids: list[str],
        rendered_ids: list[str],
        stale_ids: list[str] | None = None,
        unsupported_ids: list[str] | None = None,
    ) -> DecisionCapsuleV0:
        block = ObligationBlock(
            obligation_id=rendered_ids[0] if rendered_ids else "obl-none",
            priority=1,
            title="Test obligation",
            state="open",
        )
        return DecisionCapsuleV0(
            obligation_blocks=[block],
            token_estimate=128,
            audit_inputs={
                "budget": 900,
                "open_obligation_ids": open_ids,
                "rendered_obligation_ids": rendered_ids,
                "stale_evidence_ids_seen": stale_ids or [],
                "unsupported_confirmed_assertion_ids": unsupported_ids or [],
            },
        )


if __name__ == "__main__":
    unittest.main()

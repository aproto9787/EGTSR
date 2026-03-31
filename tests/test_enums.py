import json
import unittest

from egtsr_runtime.enums import (
    AssertionStatus,
    InvalidationStatus,
    ObligationStatus,
    VerifyPhase,
)


class EnumTests(unittest.TestCase):
    def test_enum_values_round_trip(self) -> None:
        payload = {
            "obligation_status": ObligationStatus.OPEN.value,
            "assertion_status": AssertionStatus.CONFIRMED.value,
            "invalidation_status": InvalidationStatus.REVALIDATED.value,
            "verify_phase": VerifyPhase.IMPACTED_SURFACE.value,
        }

        loaded = json.loads(json.dumps(payload))

        self.assertIs(ObligationStatus(loaded["obligation_status"]), ObligationStatus.OPEN)
        self.assertIs(AssertionStatus(loaded["assertion_status"]), AssertionStatus.CONFIRMED)
        self.assertIs(
            InvalidationStatus(loaded["invalidation_status"]),
            InvalidationStatus.REVALIDATED,
        )
        self.assertIs(VerifyPhase(loaded["verify_phase"]), VerifyPhase.IMPACTED_SURFACE)


if __name__ == "__main__":
    unittest.main()

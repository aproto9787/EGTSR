import unittest

from egtsr_runtime.hooks.responses import build_allow_response, build_block_response


class HookResponsesTests(unittest.TestCase):
    def test_build_allow_response(self) -> None:
        response = build_allow_response("SessionStart", additional_context="ctx")
        self.assertEqual(response["hookSpecificOutput"]["hookEventName"], "SessionStart")
        self.assertEqual(response["hookSpecificOutput"]["additionalContext"], "ctx")
        self.assertNotIn("decision", response)
        self.assertNotIn("suppressOutput", response)

    def test_build_block_response(self) -> None:
        response = build_block_response("blocked", additional_context="ctx")
        self.assertEqual(response["decision"], "block")
        self.assertEqual(response["reason"], "blocked")
        self.assertEqual(response["hookSpecificOutput"]["additionalContext"], "ctx")

    def test_system_message_included_when_provided(self) -> None:
        allow_response = build_allow_response("SessionEnd", system_message="done")
        block_response = build_block_response("blocked", system_message="warn")

        self.assertEqual(allow_response["systemMessage"], "done")
        self.assertEqual(block_response["systemMessage"], "warn")
        self.assertTrue(allow_response["suppressOutput"])


if __name__ == "__main__":
    unittest.main()

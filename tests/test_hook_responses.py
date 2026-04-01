import unittest

from egtsr_runtime.hooks.responses import build_allow_response, build_block_response


class HookResponsesTests(unittest.TestCase):
    # -- Hooks that support hookSpecificOutput --

    def test_build_allow_response_user_prompt_submit(self) -> None:
        response = build_allow_response("UserPromptSubmit", additional_context="ctx")
        self.assertEqual(response["hookSpecificOutput"]["hookEventName"], "UserPromptSubmit")
        self.assertEqual(response["hookSpecificOutput"]["additionalContext"], "ctx")
        self.assertNotIn("decision", response)
        self.assertNotIn("suppressOutput", response)

    def test_build_allow_response_post_tool_use(self) -> None:
        response = build_allow_response("PostToolUse", additional_context="ok")
        self.assertIn("hookSpecificOutput", response)
        self.assertEqual(response["hookSpecificOutput"]["hookEventName"], "PostToolUse")

    def test_build_allow_response_suppress_when_no_context(self) -> None:
        response = build_allow_response("UserPromptSubmit")
        self.assertTrue(response["suppressOutput"])
        self.assertIn("hookSpecificOutput", response)

    # -- Session hooks: no hookSpecificOutput --

    def test_build_allow_response_session_start(self) -> None:
        response = build_allow_response("SessionStart", additional_context="ctx")
        self.assertNotIn("hookSpecificOutput", response)
        self.assertEqual(response["systemMessage"], "ctx")
        self.assertNotIn("decision", response)

    def test_build_allow_response_session_end(self) -> None:
        response = build_allow_response("SessionEnd", additional_context="info")
        self.assertNotIn("hookSpecificOutput", response)
        self.assertEqual(response["systemMessage"], "info")

    def test_build_allow_response_session_end_empty(self) -> None:
        response = build_allow_response("SessionEnd")
        self.assertNotIn("hookSpecificOutput", response)
        self.assertTrue(response["suppressOutput"])

    # -- Block responses --

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

    def test_system_message_overrides_context_for_session_hooks(self) -> None:
        """When both additional_context and system_message are given for session hooks,
        system_message takes precedence (set last)."""
        response = build_allow_response(
            "SessionStart", additional_context="ctx", system_message="override"
        )
        self.assertNotIn("hookSpecificOutput", response)
        self.assertEqual(response["systemMessage"], "override")


if __name__ == "__main__":
    unittest.main()

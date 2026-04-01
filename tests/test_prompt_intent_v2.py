from __future__ import annotations

import unittest

from egtsr_runtime.compiler.prompt_intent_v2 import PromptRiskFlags, classify_prompt_intent_v2


class PromptIntentV2Tests(unittest.TestCase):
    """Unit tests for the v2 risk-flag based intent classifier."""

    # -- Korean write prompts --
    def test_korean_write_request(self) -> None:
        flags = classify_prompt_intent_v2("버그를 수정해줘")
        self.assertTrue(flags.requests_write)
        self.assertEqual(flags.raw_intent, "edit")

    def test_korean_create(self) -> None:
        flags = classify_prompt_intent_v2("새 파일을 생성해")
        self.assertTrue(flags.requests_write)

    def test_korean_refactor(self) -> None:
        flags = classify_prompt_intent_v2("이 함수를 리팩토링해줘")
        self.assertTrue(flags.requests_write)

    def test_korean_delete(self) -> None:
        flags = classify_prompt_intent_v2("불필요한 코드를 삭제해")
        self.assertTrue(flags.requests_write)

    # -- English read prompts --
    def test_english_read(self) -> None:
        flags = classify_prompt_intent_v2("show me the contents of config.py")
        self.assertTrue(flags.requests_read)
        self.assertFalse(flags.requests_write)
        self.assertEqual(flags.raw_intent, "read")

    def test_english_inspect(self) -> None:
        flags = classify_prompt_intent_v2("explain how the auth module works")
        self.assertTrue(flags.requests_inspection)
        self.assertFalse(flags.requests_write)
        self.assertEqual(flags.raw_intent, "inspect")

    # -- English write prompts --
    def test_english_write(self) -> None:
        flags = classify_prompt_intent_v2("fix the null pointer bug")
        self.assertTrue(flags.requests_write)
        self.assertEqual(flags.raw_intent, "edit")

    def test_english_implement(self) -> None:
        flags = classify_prompt_intent_v2("implement the retry logic")
        self.assertTrue(flags.requests_write)

    # -- Test prompts --
    def test_test_prompt(self) -> None:
        flags = classify_prompt_intent_v2("run the pytest suite")
        self.assertTrue(flags.requests_test)
        self.assertFalse(flags.requests_write)
        self.assertEqual(flags.raw_intent, "test")

    def test_korean_test(self) -> None:
        flags = classify_prompt_intent_v2("테스트를 실행해")
        self.assertTrue(flags.requests_test)

    # -- Mixed prompts (read + write => write-risk) --
    def test_mixed_read_write(self) -> None:
        flags = classify_prompt_intent_v2("read the file and fix the bug")
        self.assertTrue(flags.requests_read)
        self.assertTrue(flags.requests_write)
        self.assertEqual(flags.raw_intent, "edit")

    # -- Repo mutation --
    def test_repo_mutation_commit(self) -> None:
        flags = classify_prompt_intent_v2("commit the changes")
        self.assertTrue(flags.requests_repo_mutation)
        self.assertEqual(flags.raw_intent, "edit")

    def test_repo_mutation_push(self) -> None:
        flags = classify_prompt_intent_v2("git push to origin")
        self.assertTrue(flags.requests_repo_mutation)

    # -- Empty / ambiguous --
    def test_empty_prompt(self) -> None:
        flags = classify_prompt_intent_v2("")
        self.assertTrue(flags.ambiguous)
        self.assertEqual(flags.raw_intent, "ambiguous")

    def test_whitespace_only(self) -> None:
        flags = classify_prompt_intent_v2("   ")
        self.assertTrue(flags.ambiguous)

    def test_gibberish_ambiguous(self) -> None:
        flags = classify_prompt_intent_v2("asdfghjkl")
        self.assertTrue(flags.ambiguous)
        self.assertEqual(flags.raw_intent, "ambiguous")

    # -- Code pattern rules --
    def test_code_pattern_create_file(self) -> None:
        flags = classify_prompt_intent_v2("create src/utils.py with helper functions")
        self.assertTrue(flags.requests_write)

    def test_code_pattern_edit_file(self) -> None:
        flags = classify_prompt_intent_v2("edit the handler in routes/")
        self.assertTrue(flags.requests_write)


class PromptIntentV2ResumeGateTests(unittest.TestCase):
    """Test that ResumeGateService correctly handles PromptRiskFlags."""

    def _make_active_gate(self) -> object:
        from egtsr_runtime.services.resume_gate import ResumeGateState

        return ResumeGateState(
            session_id="test",
            edit_blocked=True,
            reason="test gate",
            required_rechecks=["repo_dirty"],
            updated_at="2026-01-01T00:00:00Z",
        )

    def test_v2_write_blocked(self) -> None:
        from egtsr_runtime.services.resume_gate import ResumeGateService

        gate = self._make_active_gate()
        flags = PromptRiskFlags(requests_write=True, raw_intent="edit")
        self.assertTrue(ResumeGateService.should_block_prompt(gate, flags))

    def test_v2_repo_mutation_blocked(self) -> None:
        from egtsr_runtime.services.resume_gate import ResumeGateService

        gate = self._make_active_gate()
        flags = PromptRiskFlags(requests_repo_mutation=True, raw_intent="edit")
        self.assertTrue(ResumeGateService.should_block_prompt(gate, flags))

    def test_v2_ambiguous_blocked(self) -> None:
        from egtsr_runtime.services.resume_gate import ResumeGateService

        gate = self._make_active_gate()
        flags = PromptRiskFlags(ambiguous=True, raw_intent="ambiguous")
        self.assertTrue(ResumeGateService.should_block_prompt(gate, flags))

    def test_v2_pure_read_allowed(self) -> None:
        from egtsr_runtime.services.resume_gate import ResumeGateService

        gate = self._make_active_gate()
        flags = PromptRiskFlags(requests_read=True, raw_intent="read")
        self.assertFalse(ResumeGateService.should_block_prompt(gate, flags))

    def test_v2_pure_test_allowed(self) -> None:
        from egtsr_runtime.services.resume_gate import ResumeGateService

        gate = self._make_active_gate()
        flags = PromptRiskFlags(requests_test=True, raw_intent="test")
        self.assertFalse(ResumeGateService.should_block_prompt(gate, flags))

    def test_v2_inspect_allowed(self) -> None:
        from egtsr_runtime.services.resume_gate import ResumeGateService

        gate = self._make_active_gate()
        flags = PromptRiskFlags(requests_inspection=True, raw_intent="inspect")
        self.assertFalse(ResumeGateService.should_block_prompt(gate, flags))

    def test_v1_string_compat(self) -> None:
        """v1 string-based intent still works."""
        from egtsr_runtime.services.resume_gate import ResumeGateService

        gate = self._make_active_gate()
        self.assertTrue(ResumeGateService.should_block_prompt(gate, "edit"))
        self.assertTrue(ResumeGateService.should_block_prompt(gate, "mixed"))
        self.assertFalse(ResumeGateService.should_block_prompt(gate, "read"))
        self.assertFalse(ResumeGateService.should_block_prompt(gate, "test"))

    def test_inactive_gate_allows_all(self) -> None:
        from egtsr_runtime.services.resume_gate import ResumeGateService, ResumeGateState

        gate = ResumeGateState(session_id="test", edit_blocked=False)
        flags = PromptRiskFlags(requests_write=True, raw_intent="edit")
        self.assertFalse(ResumeGateService.should_block_prompt(gate, flags))


class FailClosedEntrypointTests(unittest.TestCase):
    """Test that entrypoint _fail_response blocks for user_prompt_submit."""

    def test_user_prompt_submit_blocks(self) -> None:
        import io
        import json
        from unittest.mock import patch

        from egtsr_runtime.hooks.entrypoint import _fail_response

        buf = io.StringIO()
        with patch("builtins.print", side_effect=lambda s: buf.write(s)):
            _fail_response("user_prompt_submit", "test_error")

        result = json.loads(buf.getvalue())
        self.assertEqual(result["decision"], "block")
        self.assertIn("test_error", result["reason"])

    def test_other_hook_allows(self) -> None:
        import io
        import json
        from unittest.mock import patch

        from egtsr_runtime.hooks.entrypoint import _fail_response

        buf = io.StringIO()
        with patch("builtins.print", side_effect=lambda s: buf.write(s)):
            _fail_response("session_start", "test_error")

        result = json.loads(buf.getvalue())
        self.assertNotIn("decision", result)
        # Session hooks must not include hookSpecificOutput
        self.assertNotIn("hookSpecificOutput", result)
        self.assertEqual(result, {})


if __name__ == "__main__":
    unittest.main()

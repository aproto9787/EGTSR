import json
import unittest
from pathlib import Path

from egtsr_runtime.hooks import HookEnvelope, parse_hook_stdin


class HookParserTests(unittest.TestCase):
    fixtures_dir = Path("tests/fixtures/hooks")

    def test_parse_all_hook_fixtures(self) -> None:
        expected = {
            "session_start_startup.json": {"hook_event_name": "SessionStart", "source": "startup"},
            "session_start_resume.json": {"hook_event_name": "SessionStart", "source": "resume"},
            "session_start_compact.json": {"hook_event_name": "SessionStart", "source": "compact"},
            "user_prompt_submit_edit.json": {
                "hook_event_name": "UserPromptSubmit",
                "prompt": "Fix the failing auth refresh test",
            },
            "post_tool_use_read.json": {
                "hook_event_name": "PostToolUse",
                "tool_name": "Read",
                "tool_use_id": "toolu_123",
            },
            "session_end.json": {"hook_event_name": "SessionEnd"},
        }

        for fixture_name, fixture_expected in expected.items():
            with self.subTest(fixture=fixture_name):
                raw_text = (self.fixtures_dir / fixture_name).read_text(encoding="utf-8")
                envelope = parse_hook_stdin(raw_text)

                self.assertIsInstance(envelope, HookEnvelope)
                self.assertEqual(envelope.version, "1")
                self.assertEqual(envelope.session_id, "test-session-1")
                self.assertEqual(envelope.cwd, "/repo")
                self.assertEqual(envelope.hook_event_name, fixture_expected["hook_event_name"])
                self.assertTrue(envelope.received_at)

                if fixture_name == "session_start_startup.json":
                    self.assertEqual(envelope.transcript_path, "/tmp/transcript.jsonl")
                    self.assertIn("model", envelope.raw)
                    self.assertEqual(envelope.raw["model"], "claude-sonnet-4-6")
                else:
                    self.assertIsNone(envelope.transcript_path)

                if envelope.hook_event_name == "PostToolUse":
                    self.assertEqual(envelope.tool_name, fixture_expected["tool_name"])
                    self.assertEqual(envelope.tool_use_id, fixture_expected["tool_use_id"])
                    self.assertIsNone(envelope.prompt)
                    self.assertIn("tool_input", envelope.raw)
                    self.assertIn("tool_response", envelope.raw)
                else:
                    self.assertIsNone(envelope.tool_name)
                    self.assertIsNone(envelope.tool_use_id)

                if envelope.hook_event_name == "UserPromptSubmit":
                    self.assertEqual(envelope.prompt, fixture_expected["prompt"])
                else:
                    self.assertIsNone(envelope.prompt)

    def test_malformed_json_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            parse_hook_stdin("{not-json")

    def test_missing_required_field_raises_value_error(self) -> None:
        raw_text = json.dumps({"session_id": "s-1", "cwd": "/repo"})
        with self.assertRaises(ValueError):
            parse_hook_stdin(raw_text)

    def test_missing_optional_fields_become_none(self) -> None:
        envelope = parse_hook_stdin(
            json.dumps(
                {
                    "session_id": "s-1",
                    "cwd": "/repo",
                    "hook_event_name": "SessionEnd",
                }
            )
        )
        self.assertIsNone(envelope.transcript_path)
        self.assertIsNone(envelope.permission_mode)
        self.assertIsNone(envelope.source)
        self.assertIsNone(envelope.tool_name)
        self.assertIsNone(envelope.tool_use_id)
        self.assertIsNone(envelope.prompt)


if __name__ == "__main__":
    unittest.main()

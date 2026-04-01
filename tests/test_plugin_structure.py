import json
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
PLUGIN_ROOT = PROJECT_ROOT / ".claude-plugin"
SKILL_NAMES = [
    "egtsr-setup",
    "egtsr-status",
    "egtsr-inspect",
    "egtsr-doctor",
]
EXPECTED_HOOK_COMMANDS = {
    "SessionStart": 'PYTHONPATH="${CLAUDE_PLUGIN_ROOT:-.}" python3 -m egtsr_runtime.hooks.entrypoint session_start',
    "UserPromptSubmit": 'PYTHONPATH="${CLAUDE_PLUGIN_ROOT:-.}" python3 -m egtsr_runtime.hooks.entrypoint user_prompt_submit',
    "PostToolUse": 'PYTHONPATH="${CLAUDE_PLUGIN_ROOT:-.}" python3 -m egtsr_runtime.hooks.entrypoint post_tool_use',
    "SessionEnd": 'PYTHONPATH="${CLAUDE_PLUGIN_ROOT:-.}" python3 -m egtsr_runtime.hooks.entrypoint session_end',
}


class TestPluginStructure(unittest.TestCase):
    def test_plugin_json_exists(self):
        """plugin.json exists in .claude-plugin/"""
        self.assertTrue((PLUGIN_ROOT / "plugin.json").exists())

    def test_plugin_json_valid(self):
        """plugin.json matches simplified marketplace plugin format"""
        data = json.loads((PLUGIN_ROOT / "plugin.json").read_text())
        self.assertEqual(data["name"], "egtsr")
        self.assertEqual(
            data["description"],
            "Execution-Grounded Task-State Runtime — obligation tracking, stale quarantine, and resume safety for Claude Code",
        )
        self.assertEqual(data["version"], "0.1.1")
        self.assertEqual(data["author"], {"name": "argoss"})
        self.assertEqual(data["homepage"], "https://github.com/aproto9787/EGTSR")
        self.assertEqual(data["repository"], "https://github.com/aproto9787/EGTSR")
        self.assertEqual(data["license"], "MIT")
        self.assertNotIn("mcp", data)
        self.assertNotIn("hooks", data)
        self.assertNotIn("skills", data)

    def test_marketplace_json_valid(self):
        """marketplace.json exists and exposes egtsr plugin metadata"""
        data = json.loads((PLUGIN_ROOT / "marketplace.json").read_text())
        self.assertEqual(data["name"], "aproto9787-egtsr")
        self.assertEqual(data["owner"], {"name": "argoss"})
        self.assertEqual(
            data["metadata"],
            {
                "description": "EGTSR — Execution-Grounded Task-State Runtime for Claude Code",
                "version": "0.1.1",
            },
        )
        self.assertEqual(len(data["plugins"]), 1)
        self.assertEqual(
            data["plugins"][0],
            {
                "name": "egtsr",
                "source": "./",
                "description": "Obligation tracking, stale quarantine, and resume safety for Claude Code",
                "author": {"name": "argoss"},
            },
        )

    def test_mcp_config(self):
        """MCP config points to correct server"""
        data = json.loads((PROJECT_ROOT / ".mcp.json").read_text())
        self.assertIn("egtsr", data["mcpServers"])
        self.assertEqual(data["mcpServers"]["egtsr"]["command"], "python3")
        self.assertEqual(
            data["mcpServers"]["egtsr"]["args"],
            ["${CLAUDE_PLUGIN_ROOT:-.}/run_mcp.py"],
        )
        self.assertEqual(
            data["mcpServers"]["egtsr"]["env"]["PYTHONPATH"],
            "${CLAUDE_PLUGIN_ROOT:-.}",
        )

    def test_hooks_all_four(self):
        """All 4 hooks defined in hooks/hooks.json"""
        data = json.loads((PROJECT_ROOT / "hooks" / "hooks.json").read_text())
        hooks = data["hooks"]
        self.assertEqual(set(hooks), set(EXPECTED_HOOK_COMMANDS))
        for hook_name, command in EXPECTED_HOOK_COMMANDS.items():
            self.assertEqual(len(hooks[hook_name]), 1)
            hook_entry = hooks[hook_name][0]
            self.assertEqual(hook_entry["matcher"], "")
            self.assertEqual(
                hook_entry["hooks"],
                [{"type": "command", "command": command}],
            )

    def test_skill_files_exist(self):
        """All skill directories contain SKILL.md"""
        for skill_name in SKILL_NAMES:
            self.assertTrue(
                (PROJECT_ROOT / "skills" / skill_name / "SKILL.md").exists(),
                f"Missing skills/{skill_name}/SKILL.md",
            )

    def test_old_flat_skill_files_removed(self):
        """Legacy flat skill markdown files were removed"""
        self.assertEqual(list((PROJECT_ROOT / "skills").glob("*.md")), [])

    def test_skill_files_have_frontmatter(self):
        """Each skill file has YAML frontmatter with name and description"""
        for skill_file in (PROJECT_ROOT / "skills").glob("*/SKILL.md"):
            content = skill_file.read_text()
            self.assertTrue(content.startswith("---"), f"{skill_file} missing frontmatter")
            self.assertIn("name:", content)
            self.assertIn("description:", content)

    def test_skill_files_user_invocable(self):
        """Each skill is marked user-invocable"""
        for skill_file in (PROJECT_ROOT / "skills").glob("*/SKILL.md"):
            content = skill_file.read_text()
            self.assertIn("user-invocable: true", content)

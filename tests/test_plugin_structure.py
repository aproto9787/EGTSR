import json
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


class TestPluginStructure(unittest.TestCase):
    def test_plugin_json_exists(self):
        """plugin.json exists in .claude-plugin/"""
        self.assertTrue((PROJECT_ROOT / ".claude-plugin" / "plugin.json").exists())

    def test_plugin_json_valid(self):
        """plugin.json is valid JSON"""
        path = PROJECT_ROOT / ".claude-plugin" / "plugin.json"
        data = json.loads(path.read_text())
        self.assertEqual(data["name"], "egtsr")
        self.assertIn("mcp", data)
        self.assertIn("hooks", data)
        self.assertIn("skills", data)

    def test_mcp_config(self):
        """MCP config points to correct server"""
        data = json.loads((PROJECT_ROOT / ".claude-plugin" / "plugin.json").read_text())
        self.assertEqual(data["mcp"]["command"], "python3")
        self.assertIn("mcp_server.server", data["mcp"]["args"])

    def test_hooks_all_four(self):
        """All 4 hooks defined"""
        data = json.loads((PROJECT_ROOT / ".claude-plugin" / "plugin.json").read_text())
        for hook in ["SessionStart", "UserPromptSubmit", "PostToolUse", "SessionEnd"]:
            self.assertIn(hook, data["hooks"])

    def test_skills_files_exist(self):
        """All skill files referenced in plugin.json exist"""
        data = json.loads((PROJECT_ROOT / ".claude-plugin" / "plugin.json").read_text())
        for skill_path in data["skills"]:
            self.assertTrue((PROJECT_ROOT / skill_path).exists(), f"Missing: {skill_path}")

    def test_skill_files_have_frontmatter(self):
        """Each skill file has YAML frontmatter with name and description"""
        for skill_file in (PROJECT_ROOT / "skills").glob("*.md"):
            content = skill_file.read_text()
            self.assertTrue(content.startswith("---"), f"{skill_file.name} missing frontmatter")
            self.assertIn("name:", content)
            self.assertIn("description:", content)

    def test_skill_files_user_invocable(self):
        """Each skill is marked user-invocable"""
        for skill_file in (PROJECT_ROOT / "skills").glob("*.md"):
            content = skill_file.read_text()
            self.assertIn("user-invocable: true", content)

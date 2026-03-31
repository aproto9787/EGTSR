import unittest

from egtsr_runtime.config import RuntimeConfig


class RuntimeConfigTests(unittest.TestCase):
    def test_runtime_config_defaults(self) -> None:
        config = RuntimeConfig(
            repo_root="/repo",
            egtsr_dir="/repo/.egtsr",
            db_path="/repo/.egtsr/session.db",
        )

        self.assertEqual(config.repo_root, "/repo")
        self.assertEqual(config.egtsr_dir, "/repo/.egtsr")
        self.assertEqual(config.db_path, "/repo/.egtsr/session.db")
        self.assertFalse(config.enable_compact_hooks)
        self.assertEqual(config.max_decision_tokens, 900)


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import unittest

from egtsr_runtime.compiler import PromptIntentClassifier


class PromptIntentClassifierTests(unittest.TestCase):
    def setUp(self) -> None:
        self.classifier = PromptIntentClassifier()

    def test_read_prompt(self) -> None:
        self.assertEqual(self.classifier.classify("read the file"), "read")

    def test_edit_prompt(self) -> None:
        self.assertEqual(self.classifier.classify("fix the bug"), "edit")

    def test_test_prompt(self) -> None:
        self.assertEqual(self.classifier.classify("run tests"), "test")

    def test_inspect_prompt(self) -> None:
        self.assertEqual(self.classifier.classify("check the status"), "inspect")

    def test_mixed_prompt(self) -> None:
        self.assertEqual(self.classifier.classify("fix the bug and run tests"), "mixed")

    def test_empty_prompt_defaults_to_mixed(self) -> None:
        self.assertEqual(self.classifier.classify(""), "mixed")


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations


class PromptIntentClassifier:
    READ_KEYWORDS = ["read", "show", "display", "print", "cat", "view", "look", "what"]
    INSPECT_KEYWORDS = ["inspect", "check", "status", "debug", "diagnose", "why", "how"]
    EDIT_KEYWORDS = [
        "fix",
        "change",
        "modify",
        "update",
        "add",
        "remove",
        "delete",
        "refactor",
        "implement",
        "create",
        "write",
        "edit",
    ]
    TEST_KEYWORDS = ["test", "run test", "verify", "assert", "check test"]

    def classify(self, prompt: str) -> str:
        """Classify prompt intent: read, inspect, edit, test, or mixed."""

        normalized = (prompt or "").strip().lower()
        if not normalized:
            return "mixed"

        matches = {
            "read": self._matches(normalized, self.READ_KEYWORDS),
            "inspect": self._matches(normalized, self.INSPECT_KEYWORDS),
            "edit": self._matches(normalized, self.EDIT_KEYWORDS),
            "test": self._matches(normalized, self.TEST_KEYWORDS),
        }
        matched = [name for name, is_match in matches.items() if is_match]
        if len(matched) != 1:
            return "mixed"
        return matched[0]

    @staticmethod
    def _matches(prompt: str, keywords: list[str]) -> bool:
        return any(keyword in prompt for keyword in keywords)

import json


class MetricsEmitter:
    def __init__(self):
        self._counters: dict[str, int] = {}

    def incr(self, name: str, value: int = 1) -> None:
        self._counters[name] = self._counters.get(name, 0) + value

    def get(self, name: str) -> int:
        return self._counters.get(name, 0)

    def export_json(self) -> dict:
        return dict(self._counters)

    def save(self, path: str) -> None:
        with open(path, "w") as f:
            json.dump(self.export_json(), f, indent=2)


# Standard counter names
COUNTER_SESSION_START = "hook_session_start_total"
COUNTER_PROMPT_SUBMIT = "hook_prompt_submit_total"
COUNTER_POST_TOOL_USE = "hook_post_tool_use_total"
COUNTER_FAIL_OPEN = "hook_fail_open_total"
COUNTER_AUDIT_FAIL = "compile_audit_fail_total"
COUNTER_EDIT_BLOCKED = "resume_edit_block_total"
COUNTER_STALE_TICKET = "stale_ticket_total"
COUNTER_OBLIGATION_REOPENED = "obligation_reopened_total"
COUNTER_VERIFY_FAIL = "verify_fail_total"
COUNTER_ATTEMPT_FAMILY = "attempt_family_created_total"

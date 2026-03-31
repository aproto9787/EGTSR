import contextlib
import io
import json
import unittest

from egtsr_runtime.jsonio import json_stdout


class JsonStdoutTests(unittest.TestCase):
    def test_json_stdout_writes_only_json(self) -> None:
        payload = {"status": "ok", "blocked": False}
        buffer = io.StringIO()

        with contextlib.redirect_stdout(buffer):
            serialized = json_stdout(payload)

        self.assertEqual(buffer.getvalue(), serialized)
        self.assertEqual(json.loads(buffer.getvalue()), payload)


if __name__ == "__main__":
    unittest.main()

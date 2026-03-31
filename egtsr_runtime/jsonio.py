import json
import sys


def json_stdout(payload: dict) -> str:
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write(serialized)
    sys.stdout.flush()
    return serialized

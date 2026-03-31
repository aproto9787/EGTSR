import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone


@dataclass(slots=True)
class RuntimeLogEvent:
    ts: str
    level: str  # DEBUG/INFO/WARN/ERROR
    event_type: str
    session_id: str | None = None
    details: dict | None = None


class RuntimeLogger:
    def __init__(self, log_path: str):
        self._log_path = log_path

    def log(self, event: RuntimeLogEvent) -> None:
        """Append structured JSON log line to runtime.log"""
        with open(self._log_path, "a") as f:
            f.write(json.dumps(asdict(event), ensure_ascii=False) + "\n")

    def info(self, event_type: str, session_id: str | None = None, **details) -> None:
        self.log(RuntimeLogEvent(ts=datetime.now(timezone.utc).isoformat(),
                                 level="INFO", event_type=event_type,
                                 session_id=session_id, details=details or None))

    def warn(self, event_type: str, session_id: str | None = None, **details) -> None:
        self.log(RuntimeLogEvent(ts=datetime.now(timezone.utc).isoformat(),
                                 level="WARN", event_type=event_type,
                                 session_id=session_id, details=details or None))

    def error(self, event_type: str, session_id: str | None = None, **details) -> None:
        self.log(RuntimeLogEvent(ts=datetime.now(timezone.utc).isoformat(),
                                 level="ERROR", event_type=event_type,
                                 session_id=session_id, details=details or None))

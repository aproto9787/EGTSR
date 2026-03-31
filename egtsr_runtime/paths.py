from dataclasses import dataclass
from pathlib import Path

from egtsr_runtime.constants import (
    DB_FILENAME,
    DEBUG_DIR,
    EGTSR_DIR_NAME,
    LAST_GOOD_CAPSULE,
    LOG_FILENAME,
    RAW_EVENTS_DIR,
    REPORTS_DIR,
    RESUME_GATE,
)


@dataclass(slots=True, frozen=True)
class RuntimePaths:
    repo_root: str
    egtsr_dir: str
    db_path: str
    log_path: str
    last_good_capsule_path: str
    resume_gate_path: str
    raw_events_dir: str
    debug_dir: str
    reports_dir: str


def ensure_runtime_dirs(repo_root: str) -> RuntimePaths:
    root = Path(repo_root).expanduser().resolve()
    egtsr_dir = root / EGTSR_DIR_NAME
    raw_events_dir = egtsr_dir / RAW_EVENTS_DIR
    debug_dir = egtsr_dir / DEBUG_DIR
    reports_dir = egtsr_dir / REPORTS_DIR

    egtsr_dir.mkdir(parents=True, exist_ok=True)
    raw_events_dir.mkdir(exist_ok=True)
    debug_dir.mkdir(exist_ok=True)
    reports_dir.mkdir(exist_ok=True)

    return RuntimePaths(
        repo_root=str(root),
        egtsr_dir=str(egtsr_dir),
        db_path=str(egtsr_dir / DB_FILENAME),
        log_path=str(egtsr_dir / LOG_FILENAME),
        last_good_capsule_path=str(egtsr_dir / LAST_GOOD_CAPSULE),
        resume_gate_path=str(egtsr_dir / RESUME_GATE),
        raw_events_dir=str(raw_events_dir),
        debug_dir=str(debug_dir),
        reports_dir=str(reports_dir),
    )

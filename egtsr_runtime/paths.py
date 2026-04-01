from dataclasses import dataclass


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
    daemon_dir: str = ""
    exports_dir: str = ""


def ensure_runtime_dirs(repo_root: str) -> RuntimePaths:
    """Resolve project runtime paths via global EGTSR_HOME locator."""
    from egtsr_runtime.runtime_locator import resolve_project_runtime_paths

    return resolve_project_runtime_paths(repo_root)

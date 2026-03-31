from dataclasses import dataclass


@dataclass(slots=True)
class RuntimeConfig:
    repo_root: str
    egtsr_dir: str
    db_path: str
    enable_compact_hooks: bool = False
    max_decision_tokens: int = 900

"""Run the EGTSR daemon: ``python -m egtsr_runtime.daemon <repo_root>``."""
from __future__ import annotations

import sys


def main() -> None:
    if len(sys.argv) < 2:
        print(
            "Usage: python -m egtsr_runtime.daemon <repo_root> [--idle-timeout SECS]",
            file=sys.stderr,
        )
        sys.exit(1)

    repo_root = sys.argv[1]
    idle_timeout = 300

    if "--idle-timeout" in sys.argv:
        idx = sys.argv.index("--idle-timeout")
        if idx + 1 < len(sys.argv):
            try:
                idle_timeout = int(sys.argv[idx + 1])
            except ValueError:
                pass

    from egtsr_runtime.daemon.server import run_daemon

    run_daemon(repo_root, idle_timeout)


if __name__ == "__main__":
    main()

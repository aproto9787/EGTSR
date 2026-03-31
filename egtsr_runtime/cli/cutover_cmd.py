"""CLI handlers for cutover, rollback, and release check commands."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from egtsr_runtime.constants import EGTSR_DIR_NAME, REPORTS_DIR


def run_cutover_status(project_dir: str) -> int:
    from egtsr_runtime.compat.cutover import CutoverManager

    egtsr_dir = str(Path(project_dir).resolve() / EGTSR_DIR_NAME)
    mgr = CutoverManager(egtsr_dir)
    state = mgr.status()
    flags = mgr.stage_flags(state.current_stage)

    output = {
        "current_stage": state.current_stage,
        "flags": flags,
        "history_count": len(state.history),
    }
    if state.history:
        output["last_action"] = state.history[-1].to_dict()

    print(json.dumps(output, indent=2, ensure_ascii=False))
    return 0


def run_cutover_advance(project_dir: str) -> int:
    from egtsr_runtime.compat.cutover import CutoverManager

    egtsr_dir = str(Path(project_dir).resolve() / EGTSR_DIR_NAME)
    mgr = CutoverManager(egtsr_dir)
    try:
        state = mgr.advance()
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({
        "action": "advance",
        "stage": state.current_stage,
        "flags": mgr.stage_flags(state.current_stage),
    }, indent=2, ensure_ascii=False))
    return 0


def run_cutover_set(stage: str, project_dir: str) -> int:
    from egtsr_runtime.compat.cutover import CutoverManager

    egtsr_dir = str(Path(project_dir).resolve() / EGTSR_DIR_NAME)
    mgr = CutoverManager(egtsr_dir)
    try:
        state = mgr.set_stage(stage)  # type: ignore[arg-type]
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps({
        "action": "set",
        "stage": state.current_stage,
        "flags": mgr.stage_flags(state.current_stage),
    }, indent=2, ensure_ascii=False))
    return 0


def run_rollback(level: str, project_dir: str) -> int:
    from egtsr_runtime.compat.cutover import CutoverManager

    egtsr_dir = str(Path(project_dir).resolve() / EGTSR_DIR_NAME)
    mgr = CutoverManager(egtsr_dir)

    # Stop daemon if running
    _try_stop_daemon(egtsr_dir)

    state = mgr.rollback(level=level)  # type: ignore[arg-type]

    print(json.dumps({
        "action": "rollback",
        "level": level,
        "stage": state.current_stage,
        "flags": mgr.stage_flags(state.current_stage),
    }, indent=2, ensure_ascii=False))
    return 0


def run_release_check(project_dir: str, save_report: bool = False) -> int:
    from egtsr_runtime.compat.release_check import ReleaseChecker, save_release_report

    egtsr_dir = str(Path(project_dir).resolve() / EGTSR_DIR_NAME)
    checker = ReleaseChecker(egtsr_dir)
    report = checker.run_all()

    if save_report:
        reports_dir = str(Path(egtsr_dir) / REPORTS_DIR)
        path = save_release_report(report, reports_dir)
        print(f"Report saved: {path}", file=sys.stderr)

    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False))

    status = "PASS" if report.overall_pass else "FAIL"
    failed = [c for c in report.checks if not c.passed]
    print(f"\n--- Release Check: {status} ---", file=sys.stderr)
    if failed:
        for c in failed:
            print(f"  FAIL: {c.name} — {c.detail}", file=sys.stderr)

    return 0 if report.overall_pass else 1


def _try_stop_daemon(egtsr_dir: str) -> None:
    """Best-effort daemon shutdown during rollback."""
    try:
        from egtsr_runtime.daemon.client import send_shutdown
        from egtsr_runtime.daemon.registry import read_control

        info = read_control(egtsr_dir)
        if info is not None:
            send_shutdown(egtsr_dir)
    except Exception:
        pass

"""EGTSR CLI — plugin management for Claude Code.

Usage:
  egtsr setup [--project-dir PATH]      Register hooks in project
  egtsr doctor [--project-dir PATH]     Diagnose runtime health
  egtsr inspect <command> <session_id> [--project-dir PATH]  Inspect session state
  egtsr benchmark [--project-dir PATH]  Run benchmark harness
  egtsr benchmark latency [--project-dir PATH]   Hook latency benchmark
  egtsr benchmark latency-pct [--iterations N] [--project-dir PATH]  Latency percentiles
  egtsr benchmark cold-warm [--project-dir PATH] Cold vs warm daemon latency
  egtsr benchmark scale [--project-dir PATH]     Scale benchmark
  egtsr benchmark shadow-diff [--project-dir PATH]  Shadow diff benchmark
  egtsr benchmark migration [--project-dir PATH] Migration/backfill benchmark
  egtsr benchmark gate [--baseline PATH] [--project-dir PATH]  Regression gate
  egtsr metrics [--project-dir PATH]    Show aggregated runtime metrics
  egtsr daemon start [--project-dir PATH]  Start resident hook daemon
  egtsr daemon stop [--project-dir PATH]   Stop daemon
  egtsr daemon status [--project-dir PATH] Show daemon status
  egtsr cutover status [--project-dir PATH]    Show cutover stage
  egtsr cutover advance [--project-dir PATH]   Advance to next stage
  egtsr cutover set <stage> [--project-dir PATH]  Set specific stage
  egtsr rollback [--level minimal|medium|full] [--project-dir PATH]  Rollback
  egtsr release check [--save-report] [--project-dir PATH]  Release checklist
  egtsr uninstall [--project-dir PATH]  Remove hooks from project
  egtsr --version                       Show version
  egtsr --help                          Show help
"""
from __future__ import annotations

import argparse
import json
import sys
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from egtsr_runtime import __version__ as package_version
from egtsr_runtime.cli.benchmark_cmd import (
    run_benchmark,
    run_benchmark_cold_warm,
    run_benchmark_gate,
    run_benchmark_latency,
    run_benchmark_latency_percentiles,
    run_benchmark_migration,
    run_benchmark_scale,
    run_benchmark_shadow_diff,
    run_metrics,
)
from egtsr_runtime.cli.cutover_cmd import (
    run_cutover_advance,
    run_cutover_set,
    run_cutover_status,
    run_release_check,
    run_rollback,
)
from egtsr_runtime.cli.inspect_cmd import run_inspect
from egtsr_runtime.cli.setup import run_setup
from egtsr_runtime.cli.uninstall import run_uninstall
from egtsr_runtime.constants import EGTSR_DIR_NAME, REPORTS_DIR
from egtsr_runtime.ops.recovery_cli import RecoveryCLI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="egtsr", description="EGTSR Runtime for Claude Code")
    parser.add_argument("--version", action="store_true", help="Show EGTSR version and exit")
    subparsers = parser.add_subparsers(dest="command")

    setup_p = subparsers.add_parser("setup", help="Register EGTSR hooks in project")
    setup_p.add_argument("--project-dir", default=".", help="Project directory")

    doctor_p = subparsers.add_parser("doctor", help="Diagnose runtime health")
    doctor_p.add_argument("--project-dir", default=".", help="Project directory")

    inspect_p = subparsers.add_parser("inspect", help="Inspect session state")
    inspect_p.add_argument("target", choices=["obligations", "stale", "capsule", "resume"])
    inspect_p.add_argument("session_id")
    inspect_p.add_argument("--project-dir", default=".", help="Project directory")

    bench_p = subparsers.add_parser("benchmark", help="Run benchmark harness")
    bench_p.add_argument("--project-dir", default=".", help="Project directory")
    bench_p.add_argument(
        "--save-report", action="store_true", default=False,
        help="Save report to .egtsr/reports/",
    )
    bench_sub = bench_p.add_subparsers(dest="bench_mode")
    bench_sub.add_parser("latency", help="Hook latency benchmark")

    latency_pct_p = bench_sub.add_parser("latency-pct", help="Latency percentiles (multi-iteration)")
    latency_pct_p.add_argument("--iterations", type=int, default=10, help="Number of iterations")

    bench_sub.add_parser("cold-warm", help="Cold vs warm daemon latency")
    bench_sub.add_parser("scale", help="Scale benchmark")
    bench_sub.add_parser("shadow-diff", help="Legacy vs candidate compile diff")
    bench_sub.add_parser("migration", help="Migration/backfill benchmark")

    gate_p = bench_sub.add_parser("gate", help="Regression gate (PASS/FAIL)")
    gate_p.add_argument("--baseline", default=None, help="Path to baseline report JSON")

    metrics_p = subparsers.add_parser("metrics", help="Show aggregated runtime metrics")
    metrics_p.add_argument("--project-dir", default=".", help="Project directory")

    daemon_p = subparsers.add_parser("daemon", help="Manage resident hook daemon")
    daemon_sub = daemon_p.add_subparsers(dest="daemon_action")
    daemon_start_p = daemon_sub.add_parser("start", help="Start daemon in background")
    daemon_start_p.add_argument("--project-dir", default=".", help="Project directory")
    daemon_start_p.add_argument(
        "--idle-timeout", type=int, default=300, help="Idle timeout in seconds"
    )
    daemon_stop_p = daemon_sub.add_parser("stop", help="Stop running daemon")
    daemon_stop_p.add_argument("--project-dir", default=".", help="Project directory")
    daemon_status_p = daemon_sub.add_parser("status", help="Show daemon status")
    daemon_status_p.add_argument("--project-dir", default=".", help="Project directory")

    # cutover
    cutover_p = subparsers.add_parser("cutover", help="Manage staged release cutover")
    cutover_sub = cutover_p.add_subparsers(dest="cutover_action")
    cutover_status_p = cutover_sub.add_parser("status", help="Show current cutover stage")
    cutover_status_p.add_argument("--project-dir", default=".", help="Project directory")
    cutover_advance_p = cutover_sub.add_parser("advance", help="Advance to next stage")
    cutover_advance_p.add_argument("--project-dir", default=".", help="Project directory")
    cutover_set_p = cutover_sub.add_parser("set", help="Set specific cutover stage")
    cutover_set_p.add_argument("stage", choices=["baseline", "A", "B", "C", "D"])
    cutover_set_p.add_argument("--project-dir", default=".", help="Project directory")

    # rollback
    rollback_p = subparsers.add_parser("rollback", help="Rollback to legacy mode")
    rollback_p.add_argument(
        "--level", choices=["minimal", "medium", "full"], default="full",
        help="Rollback level (default: full)",
    )
    rollback_p.add_argument("--project-dir", default=".", help="Project directory")

    # release
    release_p = subparsers.add_parser("release", help="Release management")
    release_sub = release_p.add_subparsers(dest="release_action")
    release_check_p = release_sub.add_parser("check", help="Run release checklist")
    release_check_p.add_argument("--project-dir", default=".", help="Project directory")
    release_check_p.add_argument(
        "--save-report", action="store_true", default=False,
        help="Save report to .egtsr/reports/",
    )

    uninstall_p = subparsers.add_parser("uninstall", help="Remove EGTSR hooks from project")
    uninstall_p.add_argument("--project-dir", default=".", help="Project directory")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.version:
        print(_resolve_version())
        return 0

    if args.command == "setup":
        run_setup(args.project_dir)
        return 0

    if args.command == "doctor":
        result = RecoveryCLI().doctor(args.project_dir)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 1 if result.get("issues") else 0

    if args.command == "inspect":
        run_inspect(args.target, args.session_id, project_dir=args.project_dir)
        return 0

    if args.command == "benchmark":
        reports_dir = _reports_dir(args.project_dir) if args.save_report else None
        mode = getattr(args, "bench_mode", None)
        if mode == "latency":
            run_benchmark_latency(reports_dir)
        elif mode == "latency-pct":
            iterations = getattr(args, "iterations", 10)
            run_benchmark_latency_percentiles(iterations=iterations, reports_dir=reports_dir)
        elif mode == "cold-warm":
            run_benchmark_cold_warm(reports_dir)
        elif mode == "scale":
            run_benchmark_scale(reports_dir)
        elif mode == "shadow-diff":
            run_benchmark_shadow_diff(reports_dir)
        elif mode == "migration":
            run_benchmark_migration(reports_dir)
        elif mode == "gate":
            baseline_path = getattr(args, "baseline", None)
            return run_benchmark_gate(baseline_path=baseline_path, reports_dir=reports_dir)
        else:
            run_benchmark(args.project_dir)
        return 0

    if args.command == "metrics":
        metrics_dir = str(
            Path(args.project_dir).resolve() / EGTSR_DIR_NAME / "metrics"
        )
        run_metrics(metrics_dir)
        return 0

    if args.command == "daemon":
        return _handle_daemon(args)

    if args.command == "cutover":
        return _handle_cutover(args)

    if args.command == "rollback":
        return run_rollback(args.level, args.project_dir)

    if args.command == "release":
        return _handle_release(args)

    if args.command == "uninstall":
        run_uninstall(args.project_dir)
        return 0

    parser.print_help()
    return 0


def _handle_daemon(args) -> int:
    """Handle ``egtsr daemon {start|stop|status}``."""
    action = getattr(args, "daemon_action", None)
    project_dir = getattr(args, "project_dir", ".")
    egtsr_dir = str(Path(project_dir).resolve() / EGTSR_DIR_NAME)

    if action == "start":
        return _daemon_start(project_dir, getattr(args, "idle_timeout", 300))
    if action == "stop":
        return _daemon_stop(egtsr_dir)
    if action == "status":
        return _daemon_status(egtsr_dir)

    print("Usage: egtsr daemon {start|stop|status}")
    return 1


def _daemon_start(project_dir: str, idle_timeout: int) -> int:
    import subprocess

    repo_root = str(Path(project_dir).resolve())
    try:
        subprocess.Popen(
            [sys.executable, "-m", "egtsr_runtime.daemon", repo_root,
             "--idle-timeout", str(idle_timeout)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as exc:
        print(f"Failed to start daemon: {exc}")
        return 1

    import time
    from egtsr_runtime.daemon.client import send_ping

    egtsr_dir = str(Path(repo_root) / EGTSR_DIR_NAME)
    for _ in range(10):
        time.sleep(0.2)
        if send_ping(egtsr_dir):
            print(f"Daemon started (repo: {repo_root})")
            return 0
    print("Daemon process started but health check failed")
    return 1


def _daemon_stop(egtsr_dir: str) -> int:
    from egtsr_runtime.daemon.client import send_shutdown
    from egtsr_runtime.daemon.registry import read_control

    info = read_control(egtsr_dir)
    if info is None:
        print("No daemon running")
        return 0
    if send_shutdown(egtsr_dir):
        print("Daemon stopped")
        return 0
    print("Failed to stop daemon")
    return 1


def _daemon_status(egtsr_dir: str) -> int:
    from egtsr_runtime.daemon.client import send_ping
    from egtsr_runtime.daemon.registry import is_pid_alive, read_control

    info = read_control(egtsr_dir)
    if info is None:
        print(json.dumps({"status": "not_running"}, indent=2))
        return 0
    alive = is_pid_alive(info.pid)
    responsive = send_ping(egtsr_dir) if alive else False
    status = {
        "status": "running" if responsive else "stale" if not alive else "unresponsive",
        "pid": info.pid,
        "transport": info.transport,
        "socket_path": info.socket_path,
        "started_at": info.started_at,
        "repo_root": info.repo_root,
    }
    print(json.dumps(status, indent=2))
    return 0


def _handle_cutover(args) -> int:
    """Handle ``egtsr cutover {status|advance|set}``."""
    action = getattr(args, "cutover_action", None)
    project_dir = getattr(args, "project_dir", ".")
    if action == "status":
        return run_cutover_status(project_dir)
    if action == "advance":
        return run_cutover_advance(project_dir)
    if action == "set":
        return run_cutover_set(args.stage, project_dir)
    print("Usage: egtsr cutover {status|advance|set}")
    return 1


def _handle_release(args) -> int:
    """Handle ``egtsr release {check}``."""
    action = getattr(args, "release_action", None)
    if action == "check":
        project_dir = getattr(args, "project_dir", ".")
        save = getattr(args, "save_report", False)
        return run_release_check(project_dir, save_report=save)
    print("Usage: egtsr release {check}")
    return 1


def _reports_dir(project_dir: str) -> str:
    p = Path(project_dir).resolve() / EGTSR_DIR_NAME / REPORTS_DIR
    p.mkdir(parents=True, exist_ok=True)
    return str(p)


def _resolve_version() -> str:
    try:
        return version("egtsr-runtime")
    except PackageNotFoundError:
        return package_version


if __name__ == "__main__":
    sys.exit(main())

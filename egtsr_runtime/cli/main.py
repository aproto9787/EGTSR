"""EGTSR CLI — plugin management for Claude Code.

Usage:
  egtsr setup [--project-dir PATH]      Register hooks in project
  egtsr doctor [--project-dir PATH]     Diagnose runtime health
  egtsr inspect <command> <session_id> [--project-dir PATH]  Inspect session state
  egtsr benchmark [--project-dir PATH]  Run benchmark harness
  egtsr uninstall [--project-dir PATH]  Remove hooks from project
  egtsr --version                       Show version
  egtsr --help                          Show help
"""
from __future__ import annotations

import argparse
import json
import sys
from importlib.metadata import PackageNotFoundError, version

from egtsr_runtime import __version__ as package_version
from egtsr_runtime.cli.benchmark_cmd import run_benchmark
from egtsr_runtime.cli.inspect_cmd import run_inspect
from egtsr_runtime.cli.setup import run_setup
from egtsr_runtime.cli.uninstall import run_uninstall
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
        run_benchmark(args.project_dir)
        return 0

    if args.command == "uninstall":
        run_uninstall(args.project_dir)
        return 0

    parser.print_help()
    return 0


def _resolve_version() -> str:
    try:
        return version("egtsr-runtime")
    except PackageNotFoundError:
        return package_version


if __name__ == "__main__":
    sys.exit(main())

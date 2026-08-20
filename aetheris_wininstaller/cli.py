"""Command line entry point for the Aetheris Windows Installer."""

from __future__ import annotations

import argparse
import sys

from pathlib import Path

from . import __version__
from .deps import DEPENDENCIES
from .options import DB_POSTGRES, DB_SQLITE, ENV_TIMING_LATER, ENV_TIMING_NOW, InstallOptions
from .tui import run_tui

DESCRIPTION = (
    "Interactive installer for the Aetheris control panel on Windows. "
    "Runs the platform as a Docker stack and manages dependencies via winget."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aetheris-windows-installer",
        description=DESCRIPTION,
        epilog="Without flags the interactive TUI wizard starts.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the commands that would run without executing them",
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=None,
        help="target directory for the project (default %%USERPROFILE%%\\aetheris)",
    )
    parser.add_argument(
        "--db",
        choices=[DB_POSTGRES, DB_SQLITE],
        default=DB_POSTGRES,
        help="database engine: postgres (default) or sqlite local .db file",
    )
    parser.add_argument(
        "--no-env",
        action="store_true",
        help="skip writing the .env file now; create it manually later",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--tui",
        action="store_true",
        help="force the interactive TUI wizard (default when no mode flag is given)",
    )
    mode.add_argument(
        "--deps",
        action="store_true",
        help="install dependencies only (all non-optional packages)",
    )
    mode.add_argument(
        "--software",
        action="store_true",
        help="install the Aetheris software stack only (clone + docker compose up)",
    )
    mode.add_argument(
        "--both",
        action="store_true",
        help="install dependencies and the software stack",
    )
    mode.add_argument(
        "--uninstall",
        action="store_true",
        help="stop the stack and remove the application directory",
    )
    mode.add_argument(
        "--status",
        action="store_true",
        help="show the running state of every stack container (docker compose ps)",
    )
    mode.add_argument(
        "--start",
        action="store_true",
        help="bring the Aetheris stack up (docker compose up -d)",
    )
    mode.add_argument(
        "--stop",
        action="store_true",
        help="stop the Aetheris stack, keeping containers and volumes",
    )
    mode.add_argument(
        "--logs",
        action="store_true",
        help="print the last --tail lines of the whole stack",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=200,
        help="number of log lines for --logs (default: 200)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    modes = (args.deps, args.software, args.both, args.uninstall, args.status, args.start, args.stop, args.logs)
    if not any(modes):
        # Default: interactive wizard (tui handles the curses fallback).
        if args.dry_run:
            parser.error(
                "--dry-run requires a mode flag "
                "(--deps, --software, --both, --uninstall, --status, --start, --stop or --logs)"
            )
        return run_tui()

    from .actions import run_action
    from .runner import print_fail, print_ok

    action = (
        "deps" if args.deps
        else "software" if args.software
        else "both" if args.both
        else "uninstall" if args.uninstall
        else "status" if args.status
        else "start" if args.start
        else "stop" if args.stop
        else "logs"
    )

    if action in ("deps", "both"):
        deps = [d for d in DEPENDENCIES if d.required]
        print(f"Installing dependencies: {', '.join(d.label for d in deps)}")
        if action == "both":
            print("Software stack (docker compose up) will follow.")
    else:
        deps = None

    install_options = InstallOptions(
        base_dir=args.dir,
        env_timing=ENV_TIMING_LATER if args.no_env else ENV_TIMING_NOW,
        db_mode=args.db,
    )
    if args.dir:
        print(f"Project directory: {args.dir}")
    if action in ("software", "both"):
        print(f"Database engine: {args.db}")
        if args.no_env:
            print(".env will not be written now; create it manually later.")
    elif action in ("status", "start", "stop", "logs"):
        print(f"Stack: {args.dir or 'default (%USERPROFILE%\\aetheris)'}  engine: {args.db}")

    steps = run_action(action, deps=deps, options=install_options, dry_run=args.dry_run, progress=print)

    # The Docker engine must be running before the stack can start; right after a
    # fresh Docker Desktop install that only happens once the user starts it and
    # logs in. In non-interactive mode those environment-dependent steps (and the
    # repo fetch) are best-effort: the run completes successfully and prints
    # guidance instead of failing (the interactive TUI still surfaces failures
    # explicitly).
    best_effort = {"docker-ready", "clone-app", "compose-up"}

    ok = True
    environment_pending = False
    for step in steps:
        result = step.result
        if result.ok:
            print_ok(f"{step.name}")
            for line in result.lines[-2:]:
                print(f"    {line}")
        else:
            print_fail(f"{step.name}")
            for line in result.lines[-3:]:
                print(f"    {line}")
            if step.name in best_effort:
                environment_pending = True
            else:
                ok = False

    if action in ("software", "both"):
        if environment_pending:
            print("Docker is not ready yet: start Docker Desktop, then re-run the")
            print("installer with --software to bring the Aetheris stack up.")
        elif not ok:
            print("The software stack could not be brought up automatically.")
            print("Fix the reported failures above, then re-run the installer.")
        else:
            print("The Aetheris software stack is in place.")
    elif action in ("status", "start", "stop", "logs"):
        if not ok:
            print("The stack command failed. Fix the reported error, then re-run.")
        elif action == "status":
            print("Stack status reported above.")
        elif action == "logs":
            print("Last log lines reported above.")
        else:
            print(f"The Aetheris stack was {'started' if action == 'start' else 'stopped'}.")

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

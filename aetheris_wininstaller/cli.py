"""Command line entry point for the Aetheris Windows Installer."""

from __future__ import annotations

import argparse
import sys

from . import __version__
from .deps import DEPENDENCIES
from .tui import run_tui

DESCRIPTION = (
    "Interactive installer for the Aetheris control plane on Windows. "
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
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not (args.deps or args.software or args.both or args.uninstall):
        # Default: interactive wizard (tui handles the curses fallback).
        if args.dry_run:
            parser.error("--dry-run requires a mode flag (--deps, --software, --both or --uninstall)")
        return run_tui()

    from .actions import run_action
    from .runner import print_fail, print_ok

    action = "deps" if args.deps else "software" if args.software else "both" if args.both else "uninstall"

    if action in ("deps", "both"):
        deps = [d for d in DEPENDENCIES if d.required]
        print(f"Installing dependencies: {', '.join(d.label for d in deps)}")
        if action == "both":
            print("Software stack (docker compose up) will follow.")
    else:
        deps = None

    steps = run_action(action, deps=deps, dry_run=args.dry_run, progress=print)
    ok = True
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
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

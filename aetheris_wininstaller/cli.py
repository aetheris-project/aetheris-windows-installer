"""Command line entry point for the Aetheris Windows Installer."""

from __future__ import annotations

import argparse
import sys
import tempfile

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
    mode.add_argument(
        "--update-stack",
        action="store_true",
        help="update the Aetheris software to the latest images (compose pull + up -d)",
    )
    mode.add_argument(
        "--update",
        action="store_true",
        help="update the installer itself to the latest release (asks for confirmation)",
    )
    mode.add_argument(
        "--update-check",
        action="store_true",
        help="check whether a newer installer release exists",
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

    modes = (
        args.deps,
        args.software,
        args.both,
        args.uninstall,
        args.status,
        args.start,
        args.stop,
        args.logs,
        args.update_stack,
        args.update,
        args.update_check,
    )
    if not any(modes):
        # Default: interactive wizard (tui handles the curses fallback).
        if args.dry_run:
            parser.error(
                "--dry-run requires a mode flag "
                "(--deps, --software, --both, --uninstall, --status, --start, --stop, "
                "--logs, --update-stack, --update or --update-check)"
            )
        return run_tui()

    from . import updater
    from .runner import confirm_continue

    if args.update_check:
        info = updater.check_for_update()
        if info is None:
            print(f"Aetheris Windows Installer v{__version__} is up to date.")
        else:
            print(f"Update available: v{info.version} (current: v{__version__})")
            print(info.browser_url)
        return 0

    if args.update:
        info = updater.check_for_update()
        if info is None:
            print(f"Aetheris Windows Installer v{__version__} is up to date.")
            return 0
        print(f"New version available: v{info.version} (current: v{__version__})")
        if not confirm_continue(f"Download v{info.version} now?"):
            print("Update cancelled.")
            return 0
        target = Path(tempfile.gettempdir()) / f"aetheris-installer-{info.version}.exe"
        print(f"Downloading v{info.version}...")
        try:
            updater.download_asset(info.asset_url, target)
        except Exception as exc:  # noqa: BLE001 - report the network failure
            print(f"error: download failed: {exc}")
            return 1
        print(f"Downloaded to {target}")
        if not confirm_continue("The installer will close and relaunch as the new version. Proceed?"):
            print("Update downloaded but not applied. Re-run --update to apply it.")
            return 0
        applied, message = updater.apply_update(target)
        print(message)
        return 0 if applied else 1

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
        else "logs" if args.logs
        else "update-stack" if args.update_stack
        else "update-installer" if args.update
        else "update-check"
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

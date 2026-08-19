"""Subprocess runner with dry-run support.

Commands are executed through subprocess with real-time output capture so
the TUI progress screen can stream lines as they appear.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field


@dataclass
class CommandResult:
    ok: bool
    returncode: int
    output: str = ""
    lines: list[str] = field(default_factory=list)


def run_command(
    args: list[str],
    *,
    cwd: str | None = None,
    dry_run: bool = False,
    quiet: bool = False,
    env: dict[str, str] | None = None,
) -> CommandResult:
    """Run a command, streaming output, and return a CommandResult.

    When quiet is True the output is captured instead of printed (used by
    the curses TUI, which renders its own screen and must not receive raw
    stdout writes).
    """
    command_line = " ".join(args)
    if dry_run:
        if not quiet:
            print(f"[dry-run] {command_line}")
        return CommandResult(ok=True, returncode=0, output=command_line)

    try:
        proc = subprocess.Popen(
            args,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:  # pragma: no cover - platform dependent
        print(f"error: could not start process: {exc}")
        return CommandResult(ok=False, returncode=-1, output=str(exc))

    lines: list[str] = []
    assert proc.stdout is not None
    for raw in proc.stdout:
        line = raw.rstrip()
        lines.append(line)
        if not quiet:
            print(line)
    returncode = proc.wait()
    result = CommandResult(
        ok=returncode == 0,
        returncode=returncode,
        output="\n".join(lines),
        lines=lines,
    )
    return result


def confirm_continue(prompt: str, default: bool = True) -> bool:
    """Ask a yes/no question on the console."""
    suffix = "[Y/n]" if default else "[y/N]"
    while True:
        try:
            answer = input(f"{prompt} {suffix} ").strip().lower()
        except EOFError:
            return default
        if answer in ("",):
            return default
        if answer in ("y", "yes"):
            return True
        if answer in ("n", "no"):
            return False
        print("Please answer y or n.")


def print_ok(msg: str) -> None:
    print(f"  [ OK ] {msg}")


def print_fail(msg: str) -> None:
    print(f"  [FAIL] {msg}", file=sys.stderr)

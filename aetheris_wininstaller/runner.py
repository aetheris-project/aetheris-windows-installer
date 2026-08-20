"""Subprocess runner with dry-run support.

Commands are executed through subprocess with real-time output capture so
the TUI progress screen can stream lines as they appear. Long-lived
commands (docker compose logs -f) use :func:`stream_command`, which calls
an on_line callback for every line and can be stopped from another thread
through a threading.Event.
"""

from __future__ import annotations

import subprocess
import sys
import threading
from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class CommandResult:
    ok: bool
    returncode: int
    output: str = ""
    lines: list[str] = field(default_factory=list)


@dataclass
class ActionStep:
    """One executed step: a name and the result of its command."""

    name: str
    result: CommandResult


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


LineCallback = Callable[[str], None]


def stream_command(
    args: list[str],
    *,
    cwd: str | None = None,
    env: dict[str, str] | None = None,
    on_line: Optional[LineCallback] = None,
    stop_event: Optional[threading.Event] = None,
    encoding: str = "utf-8",
) -> CommandResult:
    """Run a long-lived command, streaming every line to on_line.

    Designed for interactive tails such as `docker compose logs -f`: the
    process keeps running until it exits on its own or stop_event is set,
    in which case the process is terminated and the result reports a
    successful (user-initiated) stop.

    Returns a CommandResult; when the process was stopped through
    stop_event the result is ok=True with a short note.
    """
    command_line = " ".join(args)
    try:
        proc = subprocess.Popen(
            args,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding=encoding,
            errors="replace",
        )
    except OSError as exc:
        return CommandResult(ok=False, returncode=-1, output=f"could not start process: {exc}")

    lines: list[str] = []
    stopped = False
    assert proc.stdout is not None
    try:
        for raw in proc.stdout:
            if stop_event is not None and stop_event.is_set():
                stopped = True
                proc.terminate()
                break
            line = raw.rstrip()
            lines.append(line)
            if on_line is not None:
                on_line(line)
    finally:
        returncode = proc.wait()

    if stopped:
        return CommandResult(
            ok=True,
            returncode=0,
            output="follow stopped by the user",
            lines=lines,
        )
    return CommandResult(
        ok=returncode == 0,
        returncode=returncode,
        output="\n".join(lines),
        lines=lines,
    )


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

"""Curses TUI wizard, inspired by archinstall.

Keyboard model:
    Up/Down or j/k ... move the selection
    Space .............. toggle a dependency
    Enter .............. select / confirm / accept typed text
    Backspace .......... delete a character in the directory field
    Esc ............... go back (on the dir screen, letters are typed)
    Ctrl+C ............. exit

Screens:
    main    - choose an action (setup: deps/software/both/uninstall,
              manage: status/start/stop/logs, exit)
    deps    - checkbox list of dependencies (only for deps/both)
    dir     - type the target directory for the project (software/both)
    env     - write .env now or later (software/both)
    db      - postgres or local sqlite .db file (software/both)
    confirm - summary before executing
    run     - live progress while actions execute
    done    - final result with the next steps
    logs    - live console: streams `docker compose logs -f` in real time

Robustness: every element is drawn through a safe helper, so a single
character the terminal cannot render (for example box-drawing glyphs on a
console with a legacy code page) degrades gracefully instead of blanking the
whole screen. On Windows the console code page is switched to UTF-8 at
startup, and if Unicode borders fail the frame falls back to plain ASCII.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

from . import __version__
from .actions import run_action
from .deps import DEPENDENCIES, Dependency
from .options import (
    DB_POSTGRES,
    DB_SQLITE,
    ENV_TIMING_LATER,
    ENV_TIMING_NOW,
    InstallOptions,
)
from .paths import InstallPaths, detect_db_mode, home_dir
from .runner import stream_command

try:
    import curses
except ImportError:  # pragma: no cover - Windows Python without windows-curses
    curses = None  # type: ignore[assignment]

TITLE = "Aetheris Windows Installer"
SUBTITLE = "Control panel setup on Windows - Docker based"

ACTIONS = [
    ("deps", "Install dependencies only (Docker, Git, Node.js, Python)"),
    ("software", "Install Aetheris software only (Docker stack)"),
    ("both", "Install dependencies and software"),
    ("uninstall", "Uninstall Aetheris (remove stack and app directory)"),
    ("status", "Stack status (docker compose ps)"),
    ("start", "Start the Aetheris stack"),
    ("stop", "Stop the Aetheris stack (containers stay)"),
    ("logs", "Console - live stack logs (follow)"),
    ("exit", "Exit"),
]

# First index of the management section (used to draw a section header).
MANAGE_START = 4

DEPS_ACTIONS = {"deps", "both"}
OPTIONS_ACTIONS = {"software", "both"}
RUN_IMMEDIATE_ACTIONS = {"status"}
CONFIRM_ACTIONS = {"start", "stop"}
MANAGE_ACTIONS = {"status", "start", "stop", "logs"}

ENV_TIMING_OPTIONS = [
    (ENV_TIMING_NOW, "Create .env now (recommended)"),
    (ENV_TIMING_LATER, "Skip .env - I will create it later"),
]

DB_OPTIONS = [
    (DB_POSTGRES, "PostgreSQL (full database container)"),
    (DB_SQLITE, "SQLite - local .db file (recommended for tests)"),
]

# Safe key/attribute constants that work even when the curses module is
# unavailable (the tests import this module on machines without
# windows-curses, and the PyInstaller build may not bundle it).
KEY_UP = getattr(curses, "KEY_UP", 259) if curses else 259
KEY_DOWN = getattr(curses, "KEY_DOWN", 258) if curses else 258
KEY_ENTER = getattr(curses, "KEY_ENTER", 10) if curses else 10
KEY_BACKSPACE = getattr(curses, "KEY_BACKSPACE", 263) if curses else 263
A_NORMAL = getattr(curses, "A_NORMAL", 0) if curses else 0
A_BOLD = getattr(curses, "A_BOLD", 0) if curses else 0
A_DIM = getattr(curses, "A_DIM", 0) if curses else 0
A_REVERSE = getattr(curses, "A_REVERSE", 0) if curses else 0

# Color pairs (indexes into curses.init_pair).
PAIR_ACCENT = 1   # green on default (brand emerald)
PAIR_SELECTED = 2  # black on green (inverse accent)
PAIR_ERROR = 3    # red on default
PAIR_WARN = 4     # yellow on default
PAIR_DIM = 5      # white on default (dimmed)

SPINNER = ["|", "/", "-", "\\"]

NEXT_STEPS = [
    "Open http://127.0.0.1:3000 in your browser",
    "Backend API: http://127.0.0.1:8000/docs",
    "Documentation: https://aetheris-docs.vercel.app",
]


def enable_utf8_console() -> None:
    """Switch the Windows console to UTF-8 so Unicode borders render.

    Best effort: failures are ignored, the TUI still works with ASCII.
    """
    if os.name != "nt":
        return
    try:  # pragma: no cover - Windows only
        import ctypes

        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
        ctypes.windll.kernel32.SetConsoleCP(65001)
    except Exception:  # noqa: BLE001 - cosmetic, never fatal
        pass


class TuiState:
    def __init__(self) -> None:
        self.screen_name = "main"
        self.cursor = 0
        self.dep_cursor = 0
        self.option_cursor = 0
        self.selected_deps = {
            index for index, dep in enumerate(DEPENDENCIES) if dep.required
        }
        self.dir_input = str(home_dir() / "aetheris")
        self.env_timing = ENV_TIMING_NOW
        self.db_mode = DB_POSTGRES
        self.pending_action: str | None = None
        self.progress_lines: list[str] = []
        self.finished: list[tuple[str, bool]] = []
        self.final_message = ""
        self.running = False
        self.logs_following = False
        self.log_lines: list[str] = []
        self._stop_follow_event: threading.Event | None = None
        self._worker: threading.Thread | None = None
        self._log_worker: threading.Thread | None = None
        self._frame = 0
        self._colors = False
        self._unicode_borders = True

    # ------------------------------------------------------------------
    # Options
    # ------------------------------------------------------------------

    def options(self) -> InstallOptions:
        return InstallOptions(
            base_dir=Path(self.dir_input),
            env_timing=self.env_timing,
            db_mode=self.db_mode,
        )

    def pick_action(self, index: int) -> None:
        action = ACTIONS[index][0]
        if action == "exit":
            raise SystemExit(0)
        self.pending_action = action
        if action in DEPS_ACTIONS:
            self.screen_name = "deps"
            self.dep_cursor = 0
        elif action in OPTIONS_ACTIONS:
            self.screen_name = "dir"
            self.option_cursor = 0
        elif action in RUN_IMMEDIATE_ACTIONS:
            # One-shot query: no confirmation needed, straight to the run
            # screen (fast) so the ps output appears immediately.
            self.confirm_and_run()
        elif action == "logs":
            self.screen_name = "logs"
            self._start_follow()
        else:
            self.screen_name = "confirm"

    def confirm_and_run(self) -> None:
        """Start the chosen action on a worker thread and show live progress.

        The worker keeps the curses loop free to redraw, so the run screen
        animates a spinner and streams output lines while winget/docker work.
        """
        assert self.pending_action is not None
        self.screen_name = "run"
        self.progress_lines = []
        self.finished = []
        self.final_message = ""
        self.running = True
        self._worker = threading.Thread(target=self._execute, daemon=True)
        self._worker.start()

    def wait_finished(self, timeout: float = 10.0) -> None:
        """Block until the worker thread finishes (used by tests)."""
        if self._worker is not None:
            self._worker.join(timeout=timeout)
        if self._log_worker is not None:
            self._log_worker.join(timeout=timeout)

    # ------------------------------------------------------------------
    # Live logs console
    # ------------------------------------------------------------------

    def _start_follow(self) -> None:
        """Begin streaming `docker compose logs -f` on a worker thread."""
        self.log_lines = []
        self.logs_following = True
        self._stop_follow_event = threading.Event()
        self._log_worker = threading.Thread(target=self._follow_worker, daemon=True)
        self._log_worker.start()

    def _stop_follow(self) -> None:
        """Signal the follow worker to stop and wait for it to unwind."""
        if self._stop_follow_event is not None:
            self._stop_follow_event.set()
        if self._log_worker is not None:
            self._log_worker.join(timeout=2.0)
        self._log_worker = None
        self.logs_following = False

    def _follow_worker(self) -> None:
        """Stream log lines into a bounded buffer until stopped or the
        command exits on its own."""
        assert self._stop_follow_event is not None
        try:
            options = self.options()
            paths = InstallPaths.default(options.resolved_base())
            db_mode = detect_db_mode(paths.env_file) or options.db_mode
            compose_file = paths.compose_for(db_mode)
            if not compose_file.exists():
                self._append_log(
                    f"[aetheris] no compose file at {compose_file} - install the stack first."
                )
                self._append_log("[aetheris] press q to return to the menu.")
                return
            self._append_log(
                f"[aetheris] following logs: docker compose -f {compose_file.name} logs -f"
            )
            result = stream_command(
                ["docker", "compose", "-f", str(compose_file), "logs", "-f", "--tail=100", "--timestamps"],
                cwd=str(paths.app),
                on_line=self._append_log,
                stop_event=self._stop_follow_event,
            )
            if not result.ok:
                self._append_log(f"[aetheris] docker compose logs failed: {result.output}")
            elif not self._stop_follow_event.is_set():
                self._append_log("[aetheris] log stream ended - press q to return to the menu.")
        finally:
            self.logs_following = False

    def _append_log(self, line: str) -> None:
        """Append a log line, keeping the buffer bounded."""
        self.log_lines.append(line)
        if len(self.log_lines) > 400:
            del self.log_lines[: len(self.log_lines) - 400]

    def _execute(self) -> None:
        assert self.pending_action is not None
        deps = [DEPENDENCIES[i] for i in sorted(self.selected_deps)]
        try:
            steps = run_action(
                self.pending_action,
                deps=deps,
                options=self.options(),
                quiet=True,
                progress=self.progress_lines.append,
            )
            self.finished = [(step.name, step.result.ok) for step in steps]
            # Show the captured output of the last few lines per step.
            for step in steps:
                for line in step.result.lines[-3:]:
                    self.progress_lines.append(f"    {line}")
            all_ok = all(ok for _, ok in self.finished)
            self.final_message = (
                "All steps completed successfully."
                if all_ok
                else "Some steps failed. Review the output above."
            )
        finally:
            self.running = False

    # ------------------------------------------------------------------
    # Colors
    # ------------------------------------------------------------------

    def _setup_colors(self, screen) -> None:
        """Initialize color pairs; falls back to monochrome attributes."""
        self._colors = False
        try:
            if curses is not None and curses.has_colors():
                curses.start_color()
                curses.use_default_colors()
                curses.init_pair(PAIR_ACCENT, curses.COLOR_GREEN, -1)
                curses.init_pair(PAIR_SELECTED, curses.COLOR_BLACK, curses.COLOR_GREEN)
                curses.init_pair(PAIR_ERROR, curses.COLOR_RED, -1)
                curses.init_pair(PAIR_WARN, curses.COLOR_YELLOW, -1)
                curses.init_pair(PAIR_DIM, curses.COLOR_WHITE, -1)
                self._colors = True
        except curses.error:  # pragma: no cover - depends on the terminal
            self._colors = False

    def _attr(self, base: int = A_NORMAL, *, pair: int | None = None, bold: bool = False, dim: bool = False, reverse: bool = False) -> int:
        attr = base
        if self._colors and pair is not None:
            attr |= curses.color_pair(pair)
        if bold:
            attr |= A_BOLD
        if dim:
            attr |= A_DIM
        if reverse:
            attr |= A_REVERSE
        return attr

    # ------------------------------------------------------------------
    # Safe drawing primitives
    # ------------------------------------------------------------------

    def _put(self, screen, y: int, x: int, text: str, width: int, attr: int = A_NORMAL) -> bool:
        """Draw one line safely.

        Returns False if the terminal rejected the call (for example a glyph
        that cannot be encoded); the caller can then fall back to ASCII.
        Any exception while rendering a single line is contained here so one
        bad glyph can never blank the whole screen.
        """
        try:
            screen.addnstr(y, x, text, max(1, width), attr)
            return True
        except Exception:  # noqa: BLE001 - rendering must never crash the wizard
            return False

    def _borders(self, width: int) -> tuple[str, str, str]:
        if self._unicode_borders:
            return ("┌", "┐", "└")
        return ("+", "+", "+")

    def _hline(self, screen, y: int, width: int, left: str, right: str, fill: str = "─") -> None:
        self._put(screen, y, 0, left + fill * (width - 2) + right, width)

    def _draw_frame(self, screen, height: int, width: int) -> None:
        """Outer frame with the brand title embedded in the top border."""
        tl, tr, bl = self._borders(width)
        brand = " AETHERIS "
        inner = width - 2
        pad = inner - len(brand)
        left_pad = max(pad // 2, 0)
        right_pad = max(pad - left_pad, 0)
        top = f"{tl}{'─' * left_pad}{brand}{'─' * right_pad}{tr}"
        bottom = f"{bl}{'─' * (width - 2)}{'┘' if self._unicode_borders else '+'}"

        if not self._put(screen, 0, 0, top, width):
            # Unicode glyphs are unsupported in this terminal: redraw ASCII.
            self._unicode_borders = False
            tl, tr, bl = self._borders(width)
            top = f"{tl}{'-' * left_pad}{brand}{'-' * right_pad}{tr}"
            bottom = f"{bl}{'-' * (width - 2)}{'+'}"
            if not self._put(screen, 0, 0, top, width):
                return
        self._put(screen, 1, 1, TITLE, width - 2, self._attr(bold=True, pair=PAIR_ACCENT))
        self._put(screen, 2, 1, SUBTITLE, width - 2, self._attr(dim=True, pair=PAIR_DIM))
        version = f"v{__version__}"
        self._put(screen, 2, max(1, width - len(version) - 2), version, len(version) + 2,
                  self._attr(dim=True, pair=PAIR_DIM))
        self._hline(screen, 3, width, "├" if self._unicode_borders else "+",
                    "┤" if self._unicode_borders else "+")
        self._hline(screen, height - 3, width, "├" if self._unicode_borders else "+",
                    "┤" if self._unicode_borders else "+")
        self._put(screen, height - 1, 0, bottom, width)

    def _footer(self, screen, height: int, width: int, hints: str) -> None:
        self._put(screen, height - 2, 1, " " + hints, width - 2, self._attr(reverse=True))

    # ------------------------------------------------------------------
    # Drawing
    # ------------------------------------------------------------------

    def draw(self, screen) -> None:
        screen.erase()
        height, width = screen.getmaxyx()
        if height < 8 or width < 34:
            self._draw_minimal(screen, height, width)
            screen.refresh()
            return
        self._draw_frame(screen, height, width)
        if self.screen_name == "main":
            self._draw_main(screen, height, width)
        elif self.screen_name == "deps":
            self._draw_deps(screen, height, width)
        elif self.screen_name == "dir":
            self._draw_dir(screen, height, width)
        elif self.screen_name == "env":
            self._draw_env(screen, height, width)
        elif self.screen_name == "db":
            self._draw_db(screen, height, width)
        elif self.screen_name == "confirm":
            self._draw_confirm(screen, height, width)
        elif self.screen_name == "run":
            self._draw_run(screen, height, width)
        elif self.screen_name == "done":
            self._draw_done(screen, height, width)
        elif self.screen_name == "logs":
            self._draw_logs(screen, height, width)
        screen.refresh()

    def _draw_minimal(self, screen, height: int, width: int) -> None:
        """Last-resort layout for very small terminals."""
        self._put(screen, 0, 0, TITLE, width, A_BOLD)
        if self.screen_name == "main":
            for index, (_, label) in enumerate(ACTIONS):
                cursor = ">" if index == self.cursor else " "
                attr = self._attr(reverse=True) if index == self.cursor else A_NORMAL
                self._put(screen, index + 2, 0, f"{cursor} {label}", width, attr)

    def _draw_main(self, screen, height: int, width: int) -> None:
        row = 5
        self._put(screen, row, 2, "Setup", width - 4, self._attr(bold=True, pair=PAIR_ACCENT))
        row += 1
        for index, (_, label) in enumerate(ACTIONS):
            if index == MANAGE_START:
                row += 1
                self._put(screen, row, 2, "Manage the stack", width - 4,
                          self._attr(bold=True, pair=PAIR_ACCENT))
                row += 1
            selected = index == self.cursor
            cursor = ">" if selected else " "
            attr = self._attr(pair=PAIR_SELECTED, reverse=True) if selected else A_NORMAL
            self._put(screen, row, 2, f"{cursor} {label}", width - 4, attr)
            row += 1
        self._footer(screen, height, width, "Up/Down or j/k: move   Enter: select   q: quit")

    def _draw_deps(self, screen, height: int, width: int) -> None:
        row = 5
        self._put(screen, row, 2, "Select dependencies to install:", width - 4, self._attr(bold=True))
        row += 1
        for index, dep in enumerate(DEPENDENCIES):
            selected = index == self.dep_cursor
            checked = index in self.selected_deps
            marker = "[x]" if checked else "[ ]"
            cursor = ">" if selected else " "
            suffix = " (required)" if dep.required else ""
            text = f"{cursor} {marker} {dep.label}{suffix}"
            attr = self._attr(pair=PAIR_SELECTED, reverse=True) if selected else A_NORMAL
            if not selected and checked:
                attr = self._attr(pair=PAIR_ACCENT)
            self._put(screen, row, 2, text, width - 4, attr)
            row += 1
        row += 1
        for index, dep in enumerate(DEPENDENCIES):
            if dep.description:
                hint = f"  {dep.description}"
                self._put(screen, row, 2, hint, width - 4, self._attr(dim=True))
                row += 1
        self._footer(screen, height, width, "Space: toggle   Enter: continue   Esc/q: back")

    def _draw_dir(self, screen, height: int, width: int) -> None:
        row = 5
        self._put(screen, row, 2, "Target directory for the project:", width - 4, self._attr(bold=True))
        row += 2
        label = "Path: "
        self._put(screen, row, 2, label, width - 4)
        self._put(screen, row, 2 + len(label), self.dir_input, width - 4 - len(label) - 2,
                  self._attr(pair=PAIR_ACCENT, reverse=True))
        row += 2
        self._put(screen, row, 2, "Type the path, Backspace to edit, Enter to continue",
                  width - 4, self._attr(dim=True))
        self._footer(screen, height, width, "Type: edit path   Enter: continue   Esc/q: back")

    def _draw_env(self, screen, height: int, width: int) -> None:
        row = 5
        self._put(screen, row, 2, "When should the .env file be written?", width - 4, self._attr(bold=True))
        row += 1
        for index, (_, label) in enumerate(ENV_TIMING_OPTIONS):
            selected = index == self.option_cursor
            cursor = ">" if selected else " "
            attr = self._attr(pair=PAIR_SELECTED, reverse=True) if selected else A_NORMAL
            self._put(screen, row, 2, f"{cursor} {label}", width - 4, attr)
            row += 1
        row += 1
        self._put(screen, row, 2, "Writing it now keeps the stack fully configured on first boot.",
                  width - 4, self._attr(dim=True))
        self._footer(screen, height, width, "Up/Down or j/k: move   Enter: continue   Esc/q: back")

    def _draw_db(self, screen, height: int, width: int) -> None:
        row = 5
        self._put(screen, row, 2, "Which database engine should Aetheris use?", width - 4, self._attr(bold=True))
        row += 1
        for index, (_, label) in enumerate(DB_OPTIONS):
            selected = index == self.option_cursor
            cursor = ">" if selected else " "
            attr = self._attr(pair=PAIR_SELECTED, reverse=True) if selected else A_NORMAL
            self._put(screen, row, 2, f"{cursor} {label}", width - 4, attr)
            row += 1
        row += 1
        self._put(screen, row, 2, "SQLite stores data in a local .db file - ideal for tests.",
                  width - 4, self._attr(dim=True))
        self._footer(screen, height, width, "Up/Down or j/k: move   Enter: continue   Esc/q: back")

    def _draw_confirm(self, screen, height: int, width: int) -> None:
        action = self.pending_action or "software"
        labels = dict(ACTIONS)
        title = labels.get(action, action)
        row = 5
        self._put(screen, row, 2, "Confirm your choices:", width - 4, self._attr(bold=True))
        row += 1
        self._put(screen, row, 2, f"  Action: {title}", width - 4)
        row += 1
        if action in DEPS_ACTIONS:
            deps = [DEPENDENCIES[i].label for i in sorted(self.selected_deps)]
            self._put(screen, row, 2, f"  Dependencies: {', '.join(deps) or 'none'}", width - 4)
            row += 1
        if action in OPTIONS_ACTIONS:
            self._put(screen, row, 2, f"  Directory: {self.dir_input}", width - 4)
            row += 1
            env_label = dict(ENV_TIMING_OPTIONS)[self.env_timing]
            self._put(screen, row, 2, f"  .env: {env_label}", width - 4)
            row += 1
            db_label = dict(DB_OPTIONS)[self.db_mode]
            self._put(screen, row, 2, f"  Database: {db_label}", width - 4)
            row += 1
        if action in MANAGE_ACTIONS:
            options = self.options()
            paths = InstallPaths.default(options.resolved_base())
            db_mode = detect_db_mode(paths.env_file) or options.db_mode
            self._put(screen, row, 2, f"  Compose: {paths.compose_for(db_mode).name}", width - 4)
            row += 1
        row += 1
        self._put(screen, row, 2, "Enter: start   Esc/q: back", width - 4, self._attr(dim=True))
        self._footer(screen, height, width, "Enter: start   Esc/q: back to the main menu")

    def _draw_run(self, screen, height: int, width: int) -> None:
        action = self.pending_action or "software"
        labels = dict(ACTIONS)
        spinner = SPINNER[self._frame % len(SPINNER)]
        state = "Running" if self.running else "Finished"
        self._put(screen, 5, 2, f"{spinner} {state}: {labels.get(action, action)}", width - 4,
                  self._attr(bold=True, pair=PAIR_ACCENT if self.running else None))

        row = 7
        status_mode = action == "status"
        for line in self.progress_lines[- (height - 12):]:
            attr = self._status_attr(line) if status_mode else self._attr(dim=True)
            self._put(screen, row, 2, line[: width - 4], width - 4, attr)
            row += 1

        if self.finished:
            row += 1
            for name, ok in self.finished:
                status = "OK" if ok else "FAIL"
                pair = PAIR_ACCENT if ok else PAIR_ERROR
                self._put(screen, row, 2, f"  [{status}] {name}", width - 4,
                          self._attr(pair=pair, bold=ok))
                row += 1

        if not self.running:
            row += 1
            self._put(screen, row, 2, self.final_message, width - 4,
                      self._attr(bold=True, pair=PAIR_ACCENT if self.final_message.startswith("All") else PAIR_ERROR))

    def _status_attr(self, line: str) -> int:
        """Color a docker compose ps line by container state.

        Up/running -> green, Exited/exited -> red, Restarting -> yellow,
        headers and empty lines stay dim.
        """
        lowered = line.lower()
        if "restarting" in lowered or "starting" in lowered:
            return self._attr(bold=True, pair=PAIR_WARN)
        if "up" in lowered or "running" in lowered:
            return self._attr(bold=True, pair=PAIR_ACCENT)
        if "exited" in lowered or "dead" in lowered:
            return self._attr(bold=True, pair=PAIR_ERROR)
        return self._attr(dim=True)

    def _draw_logs(self, screen, height: int, width: int) -> None:
        """Live console: streamed `docker compose logs -f` output."""
        spinner = SPINNER[self._frame % len(SPINNER)]
        status = "following" if self.logs_following else "ended"
        self._put(screen, 5, 2, f"{spinner if self.logs_following else ' '} Console - live stack logs ({status})",
                  width - 4, self._attr(bold=True, pair=PAIR_ACCENT if self.logs_following else PAIR_WARN))
        self._hline(screen, 6, width, "├" if self._unicode_borders else "+",
                    "┤" if self._unicode_borders else "+")

        row = 7
        max_rows = height - 10
        for line in self.log_lines[-max_rows:]:
            self._draw_log_line(screen, row, width, line)
            row += 1

        if self.logs_following:
            hint = "q/Esc: stop following and return to the menu"
        else:
            hint = "q/Esc: return to the menu"
        self._footer(screen, height, width, hint)

    def _draw_log_line(self, screen, y: int, width: int, line: str) -> None:
        """Draw one log line, colorizing the `<service>  |` prefix."""
        text = line[: width - 4]
        if " | " in text:
            prefix, rest = text.split(" | ", 1)
            prefix_width = min(len(prefix) + 3, width - 4)
            self._put(screen, y, 2, prefix + " | ", prefix_width,
                      self._attr(bold=True, pair=PAIR_ACCENT))
            rest_x = 2 + prefix_width
            self._put(screen, y, rest_x, rest, max(width - 4 - prefix_width, 1),
                      self._attr(dim=True))
        else:
            self._put(screen, y, 2, text, width - 4, self._attr(dim=True))

    def _draw_done(self, screen, height: int, width: int) -> None:
        row = 5
        ok = self.final_message.startswith("All")
        self._put(screen, row, 2, ("SUCCESS" if ok else "FAILED"), width - 4,
                  self._attr(bold=True, pair=PAIR_ACCENT if ok else PAIR_ERROR))
        row += 2
        self._put(screen, row, 2, self.final_message, width - 4, self._attr(bold=True))
        row += 2
        if ok:
            self._put(screen, row, 2, "Next steps:", width - 4, self._attr(bold=True, pair=PAIR_ACCENT))
            row += 1
            for step in NEXT_STEPS:
                self._put(screen, row, 4, f"- {step}", width - 6)
                row += 1
        self._footer(screen, height, width, "Press any key to exit.")

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------

    def handle(self, key: int) -> None:
        if self.screen_name in ("run", "done"):
            if self.screen_name == "done" or not self.running:
                raise SystemExit(0)
            return

        enter_keys = (ord("\n"), ord("\r"), KEY_ENTER)
        back_keys = (ord("q"), ord("Q"), 27)  # q and Esc
        backspace_keys = (127, 8, KEY_BACKSPACE)

        if self.screen_name == "logs":
            if key in back_keys:
                self._stop_follow()
                self.screen_name = "main"
            return

        if self.screen_name == "main":
            if key in (KEY_UP, ord("k")):
                self.cursor = (self.cursor - 1) % len(ACTIONS)
            elif key in (KEY_DOWN, ord("j")):
                self.cursor = (self.cursor + 1) % len(ACTIONS)
            elif key in enter_keys:
                self.pick_action(self.cursor)
            elif key in back_keys:
                raise SystemExit(0)

        elif self.screen_name == "deps":
            if key in (KEY_UP, ord("k")):
                self.dep_cursor = (self.dep_cursor - 1) % len(DEPENDENCIES)
            elif key in (KEY_DOWN, ord("j")):
                self.dep_cursor = (self.dep_cursor + 1) % len(DEPENDENCIES)
            elif key == ord(" "):
                self._toggle_dep(self.dep_cursor)
            elif key in enter_keys:
                self._after_deps()
            elif key in back_keys:
                self.screen_name = "main"

        elif self.screen_name == "dir":
            if key in backspace_keys:
                self.dir_input = self.dir_input[:-1]
            elif 32 <= key < 127:
                self.dir_input += chr(key)
            elif key in enter_keys:
                self.screen_name = "env"
                self.option_cursor = 0
            elif key in back_keys:
                # For "both" the dir screen follows deps, so go back there.
                self.screen_name = "deps" if self.pending_action == "both" else "main"

        elif self.screen_name == "env":
            if key in (KEY_UP, ord("k")):
                self.option_cursor = (self.option_cursor - 1) % len(ENV_TIMING_OPTIONS)
            elif key in (KEY_DOWN, ord("j")):
                self.option_cursor = (self.option_cursor + 1) % len(ENV_TIMING_OPTIONS)
            elif key in enter_keys:
                self.env_timing = ENV_TIMING_OPTIONS[self.option_cursor][0]
                self.screen_name = "db"
                self.option_cursor = 0
            elif key in back_keys:
                self.screen_name = "dir"

        elif self.screen_name == "db":
            if key in (KEY_UP, ord("k")):
                self.option_cursor = (self.option_cursor - 1) % len(DB_OPTIONS)
            elif key in (KEY_DOWN, ord("j")):
                self.option_cursor = (self.option_cursor + 1) % len(DB_OPTIONS)
            elif key in enter_keys:
                self.db_mode = DB_OPTIONS[self.option_cursor][0]
                self.screen_name = "confirm"
            elif key in back_keys:
                self.screen_name = "env"

        elif self.screen_name == "confirm":
            if key in enter_keys:
                self.confirm_and_run()
            elif key in back_keys:
                self.screen_name = "main"

    def _after_deps(self) -> None:
        if self.pending_action in OPTIONS_ACTIONS:
            self.screen_name = "dir"
        else:
            self.screen_name = "confirm"

    def _toggle_dep(self, index: int) -> None:
        if DEPENDENCIES[index].required:
            return  # required deps cannot be deselected
        if index in self.selected_deps:
            self.selected_deps.discard(index)
        else:
            self.selected_deps.add(index)

    def run(self, screen) -> int:
        curses.curs_set(0)
        self._setup_colors(screen)
        while True:
            self.draw(screen)
            if self.running or self.logs_following:
                # Non-blocking while a worker runs: redraw for the spinner and
                # streamed log lines. Only the logs console accepts keys now.
                screen.timeout(150)
                key = screen.getch()
                if key != -1 and self.screen_name == "logs":
                    self.handle(key)
                else:
                    self._frame += 1
                continue
            if self.screen_name == "run":
                # Worker finished: move to the final summary screen.
                self.screen_name = "done"
                continue
            if self.screen_name == "logs":
                # The follow ended on its own: keep showing the buffer until
                # the user presses a key to return to the menu.
                screen.timeout(-1)
                key = screen.getch()
                self.handle(key)
                continue
            screen.timeout(-1)
            key = screen.getch()
            self.handle(key)


def run_tui() -> int:
    """Run the interactive wizard. Returns 0 on success."""
    if curses is None:
        return run_prompt_fallback()
    enable_utf8_console()
    try:
        return curses.wrapper(TuiState().run)
    except SystemExit:
        return 0
    except Exception:  # noqa: BLE001 - fall back to plain prompts on non-TTY
        return run_prompt_fallback()


def run_prompt_fallback() -> int:
    """Plain-text equivalent of the TUI for environments without curses."""
    from .options import DB_SQLITE, ENV_TIMING_LATER
    from .ui import checkbox, input_text, select

    options = [label for _, label in ACTIONS]
    choice = select("Choose an action:", options)
    action = ACTIONS[choice][0]
    if action == "exit":
        return 0

    deps: list[Dependency] = []
    if action in DEPS_ACTIONS:
        labels = []
        selected = {i for i, d in enumerate(DEPENDENCIES) if d.required}
        for dep in DEPENDENCIES:
            suffix = " (required)" if dep.required else ""
            labels.append(f"{dep.label}{suffix}")
        chosen = checkbox("Select dependencies to install:", labels, selected)
        deps = [DEPENDENCIES[i] for i in sorted(chosen)]

    install_options = InstallOptions()
    if action in OPTIONS_ACTIONS:
        install_options = InstallOptions(
            base_dir=Path(input_text(f"Target directory ({install_options.resolved_base()}): ").strip() or install_options.resolved_base()),
            env_timing=select("When should the .env be written?", [label for _, label in ENV_TIMING_OPTIONS]),
            db_mode=select("Which database engine?", [label for _, label in DB_OPTIONS]),
        )
    elif action in MANAGE_ACTIONS:
        base = input_text(f"Project directory ({install_options.resolved_base()}): ").strip()
        install_options = InstallOptions(
            base_dir=Path(base) if base else None,
            db_mode=select("Which database engine is installed?", [label for _, label in DB_OPTIONS]),
        )

    print()
    steps = run_action(action, deps=deps, options=install_options, progress=print)
    all_ok = True
    for name, result in [(s.name, s.result) for s in steps]:
        status = "OK" if result.ok else "FAIL"
        print(f"  [{status}] {name}")
        for line in result.lines[-3:]:
            print(f"         {line}")
        all_ok = all_ok and result.ok
    print()
    print("All steps completed successfully." if all_ok else "Some steps failed. Review the output above.")
    return 0 if all_ok else 1

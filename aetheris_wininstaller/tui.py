"""Curses TUI wizard, inspired by archinstall.

Keyboard model:
    Up/Down or j/k ... move the selection
    Space .............. toggle a dependency
    Enter .............. select / confirm / accept typed text
    Backspace .......... delete a character in the directory field
    Esc ............... go back (on the dir screen, letters are typed)
    Ctrl+C ............. exit

Screens:
    main    - choose an action (deps, software, both, uninstall, exit)
    deps    - checkbox list of dependencies (only for deps/both)
    dir     - type the target directory for the project (software/both)
    env     - write .env now or later (software/both)
    db      - postgres or local sqlite .db file (software/both)
    confirm - summary before executing
    run     - live progress while actions execute
"""

from __future__ import annotations

import threading
from pathlib import Path

from .actions import run_action
from .deps import DEPENDENCIES, Dependency
from .options import (
    DB_POSTGRES,
    DB_SQLITE,
    ENV_TIMING_LATER,
    ENV_TIMING_NOW,
    InstallOptions,
)
from .paths import home_dir

try:
    import curses
except ImportError:  # pragma: no cover - Windows Python without windows-curses
    curses = None  # type: ignore[assignment]

TITLE = "Aetheris Windows Installer"
SUBTITLE = "Control plane setup on Windows - Docker based"

ACTIONS = [
    ("deps", "Install dependencies only (Docker, Git, Node.js, Python)"),
    ("software", "Install Aetheris software only (Docker stack)"),
    ("both", "Install dependencies and software"),
    ("uninstall", "Uninstall Aetheris (remove stack and app directory)"),
    ("exit", "Exit"),
]

DEPS_ACTIONS = {"deps", "both"}
OPTIONS_ACTIONS = {"software", "both"}

ENV_TIMING_OPTIONS = [
    (ENV_TIMING_NOW, "Create .env now (recommended)"),
    (ENV_TIMING_LATER, "Skip .env - I will create it later"),
]

DB_OPTIONS = [
    (DB_POSTGRES, "PostgreSQL (full database container)"),
    (DB_SQLITE, "SQLite - local .db file (recommended for tests)"),
]

# Safe key constants that work even when the curses module is unavailable
# (the tests import this module on machines without windows-curses).
KEY_UP = getattr(curses, "KEY_UP", 259) if curses else 259
KEY_DOWN = getattr(curses, "KEY_DOWN", 258) if curses else 258
KEY_ENTER = getattr(curses, "KEY_ENTER", 10) if curses else 10
KEY_BACKSPACE = getattr(curses, "KEY_BACKSPACE", 263) if curses else 263

# Color pairs (indexes into curses.init_pair).
PAIR_ACCENT = 1   # green on default (brand emerald)
PAIR_SELECTED = 2  # black on green (inverse accent)
PAIR_ERROR = 3    # red on default
PAIR_WARN = 4     # yellow on default
PAIR_DIM = 5      # white on default (dimmed)

SPINNER = ["|", "/", "-", "\\"]


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
        self._worker: threading.Thread | None = None
        self._frame = 0
        self._colors = False

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

    def _attr(self, base: int = curses.A_NORMAL, *, pair: int | None = None, bold: bool = False, dim: bool = False, reverse: bool = False) -> int:
        attr = base
        if self._colors and pair is not None:
            attr |= curses.color_pair(pair)
        if bold:
            attr |= curses.A_BOLD
        if dim:
            attr |= curses.A_DIM
        if reverse:
            attr |= curses.A_REVERSE
        return attr

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
        try:
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
        except curses.error:
            pass
        screen.refresh()

    def _draw_minimal(self, screen, height: int, width: int) -> None:
        """Last-resort layout for very small terminals."""
        try:
            screen.addnstr(0, 0, TITLE, width, curses.A_BOLD)
            if self.screen_name == "main":
                for index, (_, label) in enumerate(ACTIONS):
                    cursor = ">" if index == self.cursor else " "
                    attr = self._attr(reverse=True) if index == self.cursor else curses.A_NORMAL
                    screen.addnstr(index + 2, 0, f"{cursor} {label}", width, attr)
        except curses.error:
            pass

    def _hline(self, screen, y: int, width: int, left: str, right: str, fill: str = "─") -> None:
        screen.addnstr(y, 0, left + fill * (width - 2) + right, width)

    def _draw_frame(self, screen, height: int, width: int) -> None:
        """Outer frame with the brand title embedded in the top border."""
        brand = " AETHERIS "
        inner = width - 2
        pad = inner - len(brand)
        left_pad = max(pad // 2, 0)
        right_pad = max(pad - left_pad, 0)
        screen.addnstr(0, 0, "┌" + "─" * left_pad + brand + "─" * right_pad + "┐", width)
        screen.addnstr(1, 1, TITLE, width - 2, self._attr(bold=True, pair=PAIR_ACCENT))
        screen.addnstr(2, 1, SUBTITLE, width - 2, self._attr(dim=True, pair=PAIR_DIM))
        self._hline(screen, 3, width, "├", "┤")
        self._hline(screen, height - 3, width, "├", "┤")
        screen.addnstr(height - 1, 0, "└" + "─" * (width - 2) + "┘", width)

    def _footer(self, screen, height: int, width: int, hints: str) -> None:
        screen.addnstr(height - 2, 1, " " + hints, width - 2, self._attr(reverse=True))

    def _draw_main(self, screen, height: int, width: int) -> None:
        row = 5
        screen.addnstr(row, 2, "Choose an action:", width - 4, self._attr(bold=True))
        row += 1
        for index, (_, label) in enumerate(ACTIONS):
            selected = index == self.cursor
            cursor = ">" if selected else " "
            attr = self._attr(pair=PAIR_SELECTED, reverse=True) if selected else curses.A_NORMAL
            screen.addnstr(row, 2, f"{cursor} {label}", width - 4, attr)
            row += 1
        self._footer(screen, height, width, "Up/Down or j/k: move   Enter: select   q: quit")

    def _draw_deps(self, screen, height: int, width: int) -> None:
        row = 5
        screen.addnstr(row, 2, "Select dependencies to install:", width - 4, self._attr(bold=True))
        row += 1
        for index, dep in enumerate(DEPENDENCIES):
            selected = index == self.dep_cursor
            checked = index in self.selected_deps
            marker = "[x]" if checked else "[ ]"
            cursor = ">" if selected else " "
            suffix = " (required)" if dep.required else ""
            text = f"{cursor} {marker} {dep.label}{suffix}"
            attr = self._attr(pair=PAIR_SELECTED, reverse=True) if selected else curses.A_NORMAL
            if not selected and checked:
                attr = self._attr(pair=PAIR_ACCENT)
            screen.addnstr(row, 2, text, width - 4, attr)
            row += 1
        row += 1
        for index, dep in enumerate(DEPENDENCIES):
            if dep.description:
                hint = f"  {dep.description}"
                screen.addnstr(row, 2, hint, width - 4, self._attr(dim=True))
                row += 1
        self._footer(screen, height, width, "Space: toggle   Enter: continue   Esc/q: back")

    def _draw_dir(self, screen, height: int, width: int) -> None:
        row = 5
        screen.addnstr(row, 2, "Target directory for the project:", width - 4, self._attr(bold=True))
        row += 2
        label = "Path: "
        screen.addnstr(row, 2, label, width - 4)
        screen.addnstr(row, 2 + len(label), self.dir_input, width - 4 - len(label) - 2, self._attr(pair=PAIR_ACCENT, reverse=True))
        row += 2
        screen.addnstr(row, 2, "Type the path, Backspace to edit, Enter to continue", width - 4, self._attr(dim=True))
        self._footer(screen, height, width, "Type: edit path   Enter: continue   Esc/q: back")

    def _draw_env(self, screen, height: int, width: int) -> None:
        row = 5
        screen.addnstr(row, 2, "When should the .env file be written?", width - 4, self._attr(bold=True))
        row += 1
        for index, (_, label) in enumerate(ENV_TIMING_OPTIONS):
            selected = index == self.option_cursor
            cursor = ">" if selected else " "
            attr = self._attr(pair=PAIR_SELECTED, reverse=True) if selected else curses.A_NORMAL
            screen.addnstr(row, 2, f"{cursor} {label}", width - 4, attr)
            row += 1
        row += 1
        screen.addnstr(row, 2, "Writing it now keeps the stack fully configured on first boot.", width - 4, self._attr(dim=True))
        self._footer(screen, height, width, "Up/Down or j/k: move   Enter: continue   Esc/q: back")

    def _draw_db(self, screen, height: int, width: int) -> None:
        row = 5
        screen.addnstr(row, 2, "Which database engine should Aetheris use?", width - 4, self._attr(bold=True))
        row += 1
        for index, (_, label) in enumerate(DB_OPTIONS):
            selected = index == self.option_cursor
            cursor = ">" if selected else " "
            attr = self._attr(pair=PAIR_SELECTED, reverse=True) if selected else curses.A_NORMAL
            screen.addnstr(row, 2, f"{cursor} {label}", width - 4, attr)
            row += 1
        row += 1
        screen.addnstr(row, 2, "SQLite stores data in a local .db file - ideal for tests.", width - 4, self._attr(dim=True))
        self._footer(screen, height, width, "Up/Down or j/k: move   Enter: continue   Esc/q: back")

    def _draw_confirm(self, screen, height: int, width: int) -> None:
        action = self.pending_action or "software"
        labels = dict(ACTIONS)
        title = labels.get(action, action)
        row = 5
        screen.addnstr(row, 2, "Confirm your choices:", width - 4, self._attr(bold=True))
        row += 1
        screen.addnstr(row, 2, f"  Action: {title}", width - 4)
        row += 1
        if action in DEPS_ACTIONS:
            deps = [DEPENDENCIES[i].label for i in sorted(self.selected_deps)]
            screen.addnstr(row, 2, f"  Dependencies: {', '.join(deps) or 'none'}", width - 4)
            row += 1
        if action in OPTIONS_ACTIONS:
            screen.addnstr(row, 2, f"  Directory: {self.dir_input}", width - 4)
            row += 1
            env_label = dict(ENV_TIMING_OPTIONS)[self.env_timing]
            screen.addnstr(row, 2, f"  .env: {env_label}", width - 4)
            row += 1
            db_label = dict(DB_OPTIONS)[self.db_mode]
            screen.addnstr(row, 2, f"  Database: {db_label}", width - 4)
            row += 1
        row += 1
        screen.addnstr(row, 2, "Enter: start   Esc/q: back", width - 4, self._attr(dim=True))
        self._footer(screen, height, width, "Enter: start   Esc/q: back to the main menu")

    def _draw_run(self, screen, height: int, width: int) -> None:
        action = self.pending_action or "software"
        labels = dict(ACTIONS)
        spinner = SPINNER[self._frame % len(SPINNER)]
        state = "Running" if self.running else "Finished"
        screen.addnstr(5, 2, f"{spinner} {state}: {labels.get(action, action)}", width - 4, self._attr(bold=True, pair=PAIR_ACCENT if self.running else None))

        row = 7
        for line in self.progress_lines[- (height - 12):]:
            screen.addnstr(row, 2, line[: width - 4], width - 4, self._attr(dim=True))
            row += 1

        if self.finished:
            row += 1
            for name, ok in self.finished:
                status = "OK" if ok else "FAIL"
                pair = PAIR_ACCENT if ok else PAIR_ERROR
                screen.addnstr(row, 2, f"  [{status}] {name}", width - 4, self._attr(pair=pair, bold=ok))
                row += 1

        if not self.running:
            row += 1
            screen.addnstr(row, 2, self.final_message, width - 4, self._attr(bold=True, pair=PAIR_ACCENT if self.final_message.startswith("All") else PAIR_ERROR))
            self._footer(screen, height, width, "Press any key to exit.")

    # ------------------------------------------------------------------
    # Input
    # ------------------------------------------------------------------

    def handle(self, key: int) -> None:
        if self.screen_name == "run":
            if not self.running:
                raise SystemExit(0)
            return

        enter_keys = (ord("\n"), ord("\r"), KEY_ENTER)
        back_keys = (ord("q"), ord("Q"), 27)  # q and Esc
        backspace_keys = (127, 8, KEY_BACKSPACE)

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
            if self.running:
                # Non-blocking while the worker runs: redraw for the spinner.
                screen.timeout(150)
                key = screen.getch()
                if key == -1:
                    self._frame += 1
                    continue
                if not self.running:
                    raise SystemExit(0)
                continue
            screen.timeout(-1)
            key = screen.getch()
            self.handle(key)


def run_tui() -> int:
    """Run the interactive wizard. Returns 0 on success."""
    if curses is None:
        return run_prompt_fallback()
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

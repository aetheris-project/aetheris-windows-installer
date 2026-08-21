"""Tests for the TUI state machine (no curses screen required)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aetheris_wininstaller.deps import DEPENDENCIES  # noqa: E402
from aetheris_wininstaller.options import DB_POSTGRES, DB_SQLITE, ENV_TIMING_NOW  # noqa: E402
from aetheris_wininstaller.tui import TuiState  # noqa: E402


class TestTuiState:
    def test_initial_state(self) -> None:
        state = TuiState()
        assert state.screen_name == "main"
        assert state.cursor == 0
        # Required dependencies are pre-selected.
        required = {i for i, d in enumerate(DEPENDENCIES) if d.required}
        assert state.selected_deps == required
        assert state.env_timing == ENV_TIMING_NOW
        assert state.db_mode == DB_POSTGRES
        assert state.dir_input.endswith("aetheris")

    def test_toggle_optional_dep(self) -> None:
        state = TuiState()
        optional_index = next(i for i, d in enumerate(DEPENDENCIES) if not d.required)
        assert optional_index not in state.selected_deps
        state._toggle_dep(optional_index)
        assert optional_index in state.selected_deps
        state._toggle_dep(optional_index)
        assert optional_index not in state.selected_deps

    def test_required_dep_cannot_be_toggled(self) -> None:
        state = TuiState()
        required_index = next(i for i, d in enumerate(DEPENDENCIES) if d.required)
        before = set(state.selected_deps)
        state._toggle_dep(required_index)
        assert state.selected_deps == before

    def test_pick_action_opens_deps_screen_for_deps_actions(self) -> None:
        from aetheris_wininstaller import tui

        state = TuiState()
        index = next(i for i, (action, _) in enumerate(tui.ACTIONS) if action == "both")
        state.pick_action(index)
        assert state.screen_name == "deps"
        assert state.pending_action == "both"

    def test_pick_software_opens_dir_screen(self) -> None:
        from aetheris_wininstaller import tui

        state = TuiState()
        index = next(i for i, (action, _) in enumerate(tui.ACTIONS) if action == "software")
        state.pick_action(index)
        assert state.screen_name == "dir"
        assert state.pending_action == "software"

    def test_pick_uninstall_goes_straight_to_confirm(self) -> None:
        from aetheris_wininstaller import tui

        state = TuiState()
        index = next(i for i, (action, _) in enumerate(tui.ACTIONS) if action == "uninstall")
        state.pick_action(index)
        assert state.screen_name == "confirm"
        assert state.pending_action == "uninstall"

    def test_dir_typing_and_flow(self) -> None:
        from aetheris_wininstaller import tui

        state = TuiState()
        index = next(i for i, (action, _) in enumerate(tui.ACTIONS) if action == "software")
        state.pick_action(index)
        assert state.screen_name == "dir"

        # Type a custom path by simulating printable characters.
        for ch in "C:\\myproject":
            state.handle(ord(ch))
        assert state.dir_input.endswith("C:\\myproject")

        # Backspace removes one character.
        state.handle(127)
        assert not state.dir_input.endswith("C:\\myproject")

        # Enter advances to the env screen, then to db, then to confirm.
        state.handle(ord("\n"))
        assert state.screen_name == "env"
        state.handle(ord("\n"))
        assert state.screen_name == "db"
        state.handle(ord("\n"))
        assert state.screen_name == "confirm"

    def test_back_from_dir_returns_to_deps_for_both(self) -> None:
        from aetheris_wininstaller import tui

        state = TuiState()
        index = next(i for i, (action, _) in enumerate(tui.ACTIONS) if action == "both")
        state.pick_action(index)
        assert state.screen_name == "deps"
        state._after_deps()  # deps -> dir
        assert state.screen_name == "dir"
        state.handle(27)  # Esc: back from dir
        assert state.screen_name == "deps"

    def test_back_from_dir_returns_to_main_for_software(self) -> None:
        from aetheris_wininstaller import tui

        state = TuiState()
        index = next(i for i, (action, _) in enumerate(tui.ACTIONS) if action == "software")
        state.pick_action(index)
        assert state.screen_name == "dir"
        state.handle(27)  # Esc: back from dir
        assert state.screen_name == "main"

    def test_db_selection_flows_to_confirm(self) -> None:
        from aetheris_wininstaller import tui

        state = TuiState()
        index = next(i for i, (action, _) in enumerate(tui.ACTIONS) if action == "software")
        state.pick_action(index)
        state.handle(ord("\n"))  # dir -> env
        state.handle(ord("\n"))  # env -> db
        # Select sqlite (index 1).
        state.handle(ord("j"))
        state.handle(ord("\n"))
        assert state.db_mode == DB_SQLITE
        assert state.screen_name == "confirm"

    def test_options_object_reflects_state(self) -> None:
        state = TuiState()
        options = state.options()
        assert options.db_mode == DB_POSTGRES
        assert str(options.resolved_base()).endswith("aetheris")

    def test_exit_raises(self) -> None:
        from aetheris_wininstaller import tui

        state = TuiState()
        index = next(i for i, (action, _) in enumerate(tui.ACTIONS) if action == "exit")
        try:
            state.pick_action(index)
            raised = False
        except SystemExit:
            raised = True
        assert raised

    def test_confirm_runs_and_finishes(self, monkeypatch) -> None:
        from aetheris_wininstaller import tui
        from aetheris_wininstaller.actions import ActionStep
        from aetheris_wininstaller.runner import CommandResult

        # Patch run_action so the test never touches git/docker/filesystem.
        def fake_run_action(action, *, deps=None, options=None, dry_run=False, quiet=False, progress=None):
            if progress:
                progress("fake step")
            return [
                ActionStep(name="fake-step", result=CommandResult(ok=True, returncode=0, output="ok"))
            ]

        monkeypatch.setattr(tui, "run_action", fake_run_action)

        state = TuiState()
        from aetheris_wininstaller import tui as tui_module

        index = next(i for i, (action, _) in enumerate(tui_module.ACTIONS) if action == "software")
        state.pick_action(index)
        state.handle(ord("\n"))  # dir -> env
        state.handle(ord("\n"))  # env -> db
        state.handle(ord("\n"))  # db -> confirm
        assert state.screen_name == "confirm"
        state.confirm_and_run()
        assert state.screen_name == "run"
        state.wait_finished()
        assert not state.running
        assert state.finished, "expected at least one executed step"

    def test_pick_status_starts_run_immediately(self) -> None:
        from aetheris_wininstaller import tui

        state = TuiState()
        index = next(i for i, (action, _) in enumerate(tui.ACTIONS) if action == "status")
        state.pick_action(index)
        assert state.screen_name == "run"
        assert state.pending_action == "status"
        state.wait_finished()

    def test_pick_start_goes_to_confirm(self) -> None:
        from aetheris_wininstaller import tui

        state = TuiState()
        index = next(i for i, (action, _) in enumerate(tui.ACTIONS) if action == "start")
        state.pick_action(index)
        assert state.screen_name == "confirm"
        assert state.pending_action == "start"

    def test_update_actions_are_in_the_menu(self) -> None:
        from aetheris_wininstaller import tui

        actions = [action for action, _ in tui.ACTIONS]
        assert "update-installer" in actions
        assert "update-stack" in actions
        assert actions.index("update-installer") < actions.index("exit")
        assert actions.index("update-stack") < actions.index("exit")

    def test_pick_update_stack_goes_to_confirm(self) -> None:
        from aetheris_wininstaller import tui

        state = TuiState()
        index = next(i for i, (action, _) in enumerate(tui.ACTIONS) if action == "update-stack")
        state.pick_action(index)
        assert state.screen_name == "confirm"
        assert state.pending_action == "update-stack"
        assert state.confirm_stage == 0

    def test_update_action_requires_double_confirmation(self) -> None:
        from aetheris_wininstaller import tui

        state = TuiState()
        index = next(i for i, (action, _) in enumerate(tui.ACTIONS) if action == "update-stack")
        state.pick_action(index)
        assert state.screen_name == "confirm"

        # First Enter only arms the confirmation.
        state.handle(ord("\n"))
        assert state.screen_name == "confirm"
        assert state.confirm_stage == 1
        assert state.running is False

        # Second Enter actually starts the action.
        state.handle(ord("\n"))
        assert state.screen_name == "run"

    def test_non_update_action_starts_on_first_enter(self) -> None:
        from aetheris_wininstaller import tui

        state = TuiState()
        index = next(i for i, (action, _) in enumerate(tui.ACTIONS) if action == "uninstall")
        state.pick_action(index)
        state.handle(ord("\n"))
        assert state.screen_name == "run"

    def test_update_banner_is_drawn_when_update_available(self) -> None:
        from aetheris_wininstaller import tui
        from aetheris_wininstaller.updater import UpdateInfo

        state = TuiState()
        state.update_info = UpdateInfo(
            version="9.9.9",
            asset_url="https://example.com/exe",
            browser_url="https://example.com",
            notes="",
        )
        screen = _RejectUnicodeScreen()
        state.draw(screen)
        assert any("Update available: v9.9.9" in text for _, _, text in screen.buffer)

    def test_pick_logs_opens_console_and_esc_returns(self, monkeypatch, tmp_path: Path) -> None:
        from aetheris_wininstaller import tui

        def fake_stream(*args, **kwargs):
            from aetheris_wininstaller.runner import CommandResult

            on_line = kwargs.get("on_line")
            if on_line:
                on_line("web_1  | listening on :3000")
            stop_event = kwargs.get("stop_event")
            if stop_event:
                stop_event.set()  # end the follow immediately
            return CommandResult(ok=True, returncode=0, output="ok")

        monkeypatch.setattr(tui, "stream_command", fake_stream)

        # A compose file must exist so the follow worker reaches the stream.
        app_dir = tmp_path / "aetheris-app"
        app_dir.mkdir(parents=True)
        (app_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")

        state = TuiState()
        state.dir_input = str(tmp_path)
        index = next(i for i, (action, _) in enumerate(tui.ACTIONS) if action == "logs")
        state.pick_action(index)
        assert state.screen_name == "logs"
        state.wait_finished()
        assert not state.logs_following
        assert any("listening on :3000" in line for line in state.log_lines)

        state.handle(27)  # Esc: back to the menu
        assert state.screen_name == "main"

    def test_utf8_console_enabler_is_best_effort(self, monkeypatch) -> None:
        """enable_utf8_console never raises, even on non-Windows hosts."""
        from aetheris_wininstaller import tui

        monkeypatch.setattr(tui.os, "name", "posix")
        tui.enable_utf8_console()  # must not raise

    def test_docker_not_ready_is_guidance_not_failure(self, monkeypatch) -> None:
        """docker-ready / clone-app / compose-up failures must not show a
        hard FAILED: on a fresh machine Docker Desktop was just installed
        and needs a manual first start."""
        from aetheris_wininstaller import tui
        from aetheris_wininstaller.actions import ActionStep
        from aetheris_wininstaller.runner import CommandResult

        def fake_run_action(action, *, deps=None, options=None, dry_run=False, quiet=False, progress=None):
            return [
                ActionStep(name="dependency:Docker.DockerDesktop", result=CommandResult(ok=True, returncode=0, output="ok")),
                ActionStep(name="docker-ready", result=CommandResult(ok=False, returncode=-1, output="engine not running")),
            ]

        monkeypatch.setattr(tui, "run_action", fake_run_action)

        state = TuiState()
        state.pending_action = "both"
        state.confirm_and_run()
        state.wait_finished()
        assert "Docker is not ready yet" in state.final_message
        assert "FAILED" not in state.final_message

    def test_hard_step_failure_is_still_failure(self, monkeypatch) -> None:
        """A real dependency failure must keep showing FAILED."""
        from aetheris_wininstaller import tui
        from aetheris_wininstaller.actions import ActionStep
        from aetheris_wininstaller.runner import CommandResult

        def fake_run_action(action, *, deps=None, options=None, dry_run=False, quiet=False, progress=None):
            return [
                ActionStep(name="dependency:Git.Git", result=CommandResult(ok=False, returncode=1, output="winget failed")),
            ]

        monkeypatch.setattr(tui, "run_action", fake_run_action)

        state = TuiState()
        state.pending_action = "both"
        state.confirm_and_run()
        state.wait_finished()
        assert "Some steps failed" in state.final_message


class _RejectUnicodeScreen:
    """Fake curses screen that raises on any non-ASCII glyph."""

    def __init__(self) -> None:
        self.buffer: list[str] = []
        self.yx = (24, 80)
        self.chars = set()

    def getmaxyx(self) -> tuple[int, int]:
        return self.yx

    def erase(self) -> None:
        self.buffer = []

    def refresh(self) -> None:
        pass

    def addnstr(self, y: int, x: int, text: str, n: int, attr: int = 0) -> None:
        from aetheris_wininstaller.tui import A_BOLD

        self.chars.update(text)
        if any(ord(ch) > 127 for ch in text):
            raise ValueError("glyph not supported")
        self.buffer.append((y, x, text))


def test_draw_falls_back_to_ascii_frame() -> None:
    """A terminal that rejects Unicode borders must still render the menu."""
    from aetheris_wininstaller import tui

    state = TuiState()
    screen = _RejectUnicodeScreen()
    state.draw(screen)
    # The unicode top border failed, so the frame switches to ASCII and the
    # content still draws - the screen is not blank.
    assert state._unicode_borders is False
    assert any("AETHERIS" in text for _, _, text in screen.buffer)
    assert any("Setup" in text for _, _, text in screen.buffer)
    assert any("Manage the stack" in text for _, _, text in screen.buffer)
    assert any("Install dependencies only" in text for _, _, text in screen.buffer)
    assert any("Console - live stack logs" in text for _, _, text in screen.buffer)


def test_logs_screen_draws_console_header() -> None:
    """The live console renders its header and streamed lines."""
    from aetheris_wininstaller import tui

    state = TuiState()
    state.screen_name = "logs"
    state.logs_following = False
    state.log_lines = ["web_1  | ready", "backend_1  | uvicorn running"]
    screen = _RejectUnicodeScreen()
    state.draw(screen)
    assert any("Console - live stack logs" in text for _, _, text in screen.buffer)
    assert any("ready" in text for _, _, text in screen.buffer)
    assert any("uvicorn running" in text for _, _, text in screen.buffer)

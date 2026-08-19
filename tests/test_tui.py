"""Tests for the TUI state machine (no curses screen required)."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aetheris_wininstaller.deps import DEPENDENCIES  # noqa: E402
from aetheris_wininstaller.tui import TuiState  # noqa: E402


class TestTuiState:
    def test_initial_state(self) -> None:
        state = TuiState()
        assert state.screen_name == "main"
        assert state.cursor == 0
        # Required dependencies are pre-selected.
        required = {i for i, d in enumerate(DEPENDENCIES) if d.required}
        assert state.selected_deps == required

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

    def test_pick_software_goes_straight_to_confirm(self) -> None:
        state = TuiState()
        from aetheris_wininstaller import tui

        index = next(i for i, (action, _) in enumerate(tui.ACTIONS) if action == "software")
        state.pick_action(index)
        assert state.screen_name == "confirm"
        assert state.pending_action == "software"

    def test_exit_raises(self) -> None:
        state = TuiState()
        from aetheris_wininstaller import tui

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
        def fake_run_action(action, *, deps=None, dry_run=False, quiet=False, progress=None):
            if progress:
                progress("fake step")
            return [
                ActionStep(name="fake-step", result=CommandResult(ok=True, returncode=0, output="ok"))
            ]

        monkeypatch.setattr(tui, "run_action", fake_run_action)

        state = TuiState()
        index = next(i for i, (action, _) in enumerate(tui.ACTIONS) if action == "software")
        state.pick_action(index)
        assert state.screen_name == "confirm"
        state.confirm_and_run()
        assert state.screen_name == "run"
        assert not state.running
        assert state.finished, "expected at least one executed step"

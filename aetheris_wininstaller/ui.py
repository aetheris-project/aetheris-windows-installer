"""Plain-text fallback UI for terminals without curses support.

The TUI needs `windows-curses` on Windows; when it is missing this module
provides a menu/checkbox flow with the same options using plain prompts.
No emoji, no colored blocks.
"""

from __future__ import annotations

TITLE = "AETHERIS Windows Installer"
SUBTITLE = "Control plane setup on Windows - Docker based"


def _rule(width: int = 60) -> str:
    return "-" * width


def _header() -> None:
    print()
    print(f"  {TITLE}")
    print(f"  {SUBTITLE}")
    print(f"  {_rule()}")


def _print_options(options: list[str], index: int) -> None:
    for position, option in enumerate(options):
        marker = ">" if position == index else " "
        print(f" {marker} {position + 1}. {option}")


def select(prompt: str, options: list[str], index: int = 0) -> int:
    _header()
    print(f"  {prompt}")
    _print_options(options, index)
    print(f"  {_rule()}")
    while True:
        raw = input(f"Select 1-{len(options)} (Enter keeps {index + 1}): ").strip()
        if raw == "":
            return index
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return int(raw) - 1
        print("Invalid selection.")


def checkbox(prompt: str, options: list[str], selected: set[int]) -> set[int]:
    """Toggle a subset of options. Returns the selected indices."""
    _header()
    print(f"  {prompt}")
    while True:
        for position, option in enumerate(options):
            marker = "[x]" if position in selected else "[ ]"
            print(f" {marker} {position + 1}. {option}")
        print(f"  {_rule()}")
        raw = input("Toggle a number (Enter to continue): ").strip()
        if raw == "":
            return selected
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            index = int(raw) - 1
            if index in selected:
                selected.discard(index)
            else:
                selected.add(index)
        else:
            print("Invalid selection.")


def input_text(prompt: str) -> str:
    """Read a line of free text from the user."""
    try:
        return input(prompt)
    except EOFError:
        return ""

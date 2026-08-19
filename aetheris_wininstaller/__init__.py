"""Aetheris Windows Installer.

Interactive, TUI-driven installer for the Aetheris control plane on Windows.
Runs the platform as a Docker stack and manages the required dependencies
(Docker Desktop, Git, Node.js LTS, Python) through winget.
"""

from __future__ import annotations

__version__ = "1.0.0"

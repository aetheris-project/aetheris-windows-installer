"""Dependency definitions for the Windows installer.

Every dependency is installed through winget with a pinned package id.
The TUI lets the user toggle optional packages; Docker Desktop and Git are
always required for the Docker-based install to work.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Dependency:
    winget_id: str
    label: str
    required: bool = False
    description: str = ""


DEPENDENCIES: tuple[Dependency, ...] = (
    Dependency(
        "Docker.DockerDesktop",
        "Docker Desktop",
        required=True,
        description="Container runtime required to run the Aetheris stack",
    ),
    Dependency(
        "Git.Git",
        "Git for Windows",
        required=True,
        description="Version control used to fetch the Aetheris repositories",
    ),
    Dependency(
        "OpenJS.NodeJS.LTS",
        "Node.js LTS",
        description="Runtime for the Aetheris control plane (web + workers)",
    ),
    Dependency(
        "Python.Python.3.12",
        "Python 3.12",
        description="Runtime for the Aetheris Python backend",
    ),
)


def dependency_by_id(winget_id: str) -> Dependency | None:
    for dep in DEPENDENCIES:
        if dep.winget_id == winget_id:
            return dep
    return None

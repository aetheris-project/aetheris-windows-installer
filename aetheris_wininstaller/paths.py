"""Path resolution and constants for the Windows installer.

All paths are computed at runtime so the installer works for any Windows
user (including non-English usernames, which break naive assumptions about
the user profile directory).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

APP_REPO_URL = "https://github.com/aetheris-project/aetheris-app.git"
APP_REPO_NAME = "aetheris-app"

WEB_URL = "http://localhost:3000"
BACKEND_HEALTH_URL = "http://localhost:8000/health"


def home_dir() -> Path:
    profile = os.environ.get("USERPROFILE")
    if profile:
        return Path(profile)
    return Path.home()


@dataclass(frozen=True)
class InstallPaths:
    base: Path
    app: Path
    compose_file: Path
    env_file: Path

    @classmethod
    def default(cls) -> "InstallPaths":
        base = home_dir() / "aetheris"
        return cls(
            base=base,
            app=base / APP_REPO_NAME,
            compose_file=base / APP_REPO_NAME / "docker-compose.yml",
            env_file=base / APP_REPO_NAME / ".env",
        )


def is_docker_installed() -> bool:
    """Check that a docker CLI is on PATH (Docker Desktop provides it)."""
    return any(
        Path(p, "docker.exe").exists()
        for p in os.environ.get("PATH", "").split(os.pathsep)
        if p.strip()
    )

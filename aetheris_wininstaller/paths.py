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
    compose_sqlite_file: Path
    env_file: Path

    @classmethod
    def default(cls, base: Path | None = None) -> "InstallPaths":
        base = base or (home_dir() / "aetheris")
        return cls(
            base=base,
            app=base / APP_REPO_NAME,
            compose_file=base / APP_REPO_NAME / "docker-compose.yml",
            compose_sqlite_file=base / APP_REPO_NAME / "docker-compose.sqlite.yml",
            env_file=base / APP_REPO_NAME / ".env",
        )

    def compose_for(self, db_mode: str) -> Path:
        """Pick the compose file for the requested database engine."""
        if db_mode == "sqlite":
            return self.compose_sqlite_file
        return self.compose_file


def detect_db_mode(env_file: Path) -> str | None:
    """Return the database engine recorded in an existing .env, or None.

    The installer writes AETHERIS_DB_MODE=sqlite when an install uses the
    local .db file, so uninstalling can target the same compose file even
    when the user does not repeat --db.
    """
    if not env_file.exists():
        return None
    try:
        for raw in env_file.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line.startswith("AETHERIS_DB_MODE="):
                value = line.split("=", 1)[1].strip().lower()
                if value:
                    return value
    except OSError:  # pragma: no cover - read failures fall back to defaults
        return None
    return None


def is_docker_installed() -> bool:
    """Check that a docker CLI is on PATH (Docker Desktop provides it)."""
    return any(
        Path(p, "docker.exe").exists()
        for p in os.environ.get("PATH", "").split(os.pathsep)
        if p.strip()
    )

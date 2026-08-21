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


def docker_desktop_paths() -> tuple[Path, ...]:
    """Standard Docker Desktop install locations, resolved at call time so
    tests and per-user installs can vary the environment."""
    return (
        # %ProgramFiles%\Docker\Docker\resources\bin\docker.exe
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Docker" / "Docker" / "resources" / "bin" / "docker.exe",
        # %LOCALAPPDATA%\Docker\Docker\resources\bin\docker.exe (per-user install)
        Path(os.environ.get("LOCALAPPDATA", "")) / "Docker" / "Docker" / "resources" / "bin" / "docker.exe",
    )


def find_docker() -> Path | None:
    """Locate the docker CLI.

    Prefers a docker.exe already on PATH, then falls back to the standard
    Docker Desktop install locations. winget updates the registry PATH but
    never the running process, so a freshly installed Docker Desktop would
    otherwise be invisible until the next login.
    """
    for p in os.environ.get("PATH", "").split(os.pathsep):
        if p.strip():
            candidate = Path(p, "docker.exe")
            if candidate.exists():
                return candidate
    for candidate in docker_desktop_paths():
        if candidate.exists():
            return candidate
    return None


def is_docker_installed() -> bool:
    """Check that a docker CLI is available (PATH or Docker Desktop paths)."""
    return find_docker() is not None


def docker_command(*args: str) -> list[str]:
    """Build a docker command line, using the resolved docker executable."""
    docker = find_docker()
    if docker is not None:
        return [str(docker), *args]
    return ["docker", *args]

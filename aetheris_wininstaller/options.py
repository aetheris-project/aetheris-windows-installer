"""Installation options collected by the TUI or the CLI.

These mirror the decisions the wizard asks the user about:
  - where the project is installed (base directory),
  - whether the .env should be written now or left for later,
  - which database engine to use (PostgreSQL container vs local SQLite file).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .paths import home_dir

ENV_TIMING_NOW = "now"
ENV_TIMING_LATER = "later"

DB_POSTGRES = "postgres"
DB_SQLITE = "sqlite"


@dataclass(frozen=True)
class InstallOptions:
    base_dir: Path | None = None
    env_timing: str = ENV_TIMING_NOW
    db_mode: str = DB_POSTGRES

    def resolved_base(self) -> Path:
        """Return the base directory, falling back to %USERPROFILE%\\aetheris."""
        return self.base_dir or (home_dir() / "aetheris")

    @property
    def is_sqlite(self) -> bool:
        return self.db_mode == DB_SQLITE

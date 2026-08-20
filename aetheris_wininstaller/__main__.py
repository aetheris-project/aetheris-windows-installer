from __future__ import annotations

import sys

# Absolute import: PyInstaller executes this file as the top-level script,
# where a relative import (from .cli import main) has no package context and
# crashes with ImportError. The package root is on pathex in the build spec.
from aetheris_wininstaller.cli import main

if __name__ == "__main__":
    sys.exit(main())

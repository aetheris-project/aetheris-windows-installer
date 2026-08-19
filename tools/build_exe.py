"""Build the Windows executable with PyInstaller.

Produces a single-file console executable at dist/aetheris-windows-installer.exe.
The TUI needs windows-curses at runtime; PyInstaller bundles it automatically
when installed in the build environment (it is a plain import).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRY = ROOT / "aetheris_wininstaller" / "__main__.py"
DIST = ROOT / "dist"
BUILD = ROOT / "build"

SPEC = f"""# -*- mode: python ; coding: utf-8 -*-
a = Analysis(
    [r"{ENTRY}"],
    pathex=[r"{ROOT}"],
    binaries=[],
    datas=[],
    hiddenimports=["curses", "curses.textpad", "curses.ascii"],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="aetheris-windows-installer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=r"{ROOT / 'tools' / 'version_info.txt'}",
)
"""


def main() -> int:
    if shutil.which("pyinstaller") is None:
        print("pyinstaller is not installed; run: pip install pyinstaller")
        return 1

    BUILD.mkdir(exist_ok=True)
    spec_path = BUILD / "aetheris-windows-installer.spec"
    spec_path.write_text(SPEC, encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--distpath",
            str(DIST),
            "--workpath",
            str(BUILD / "work"),
            str(spec_path),
        ],
        cwd=ROOT,
    )
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())

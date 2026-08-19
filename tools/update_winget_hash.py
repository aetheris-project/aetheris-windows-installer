"""Compute the SHA-256 of the built installer and patch the winget manifest.

Usage:
    python tools/update_winget_hash.py

Reads dist/aetheris-windows-installer.exe, computes its SHA-256 digest, and
patches the InstallerSha256 field in the winget installer manifest.

Run this after building the .exe and before committing the winget manifests.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXE = ROOT / "dist" / "aetheris-windows-installer.exe"
MANIFEST = ROOT / "winget" / "AetherisProject.AetherisWindowsInstaller.installer.yaml"
PLACEHOLDER = "REPLACE_WITH_SHA256"


def sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    if not EXE.exists():
        print(f"error: {EXE} not found — build the installer first", file=sys.stderr)
        return 1
    if not MANIFEST.exists():
        print(f"error: {MANIFEST} not found", file=sys.stderr)
        return 1

    digest = sha256_of_file(EXE)
    print(f"SHA-256: {digest}")

    content = MANIFEST.read_text(encoding="utf-8")
    if PLACEHOLDER not in content:
        print("warning: placeholder already replaced — checking if hash matches")
        # Extract existing hash line
        for line in content.splitlines():
            if "InstallerSha256:" in line:
                existing = line.split(":", 1)[1].strip()
                if existing == digest:
                    print("hash matches manifest — nothing to do")
                    return 0
                else:
                    print(f"manifest has {existing}, exe has {digest} — updating")
                    content = content.replace(existing, digest)
                    MANIFEST.write_text(content, encoding="utf-8")
                    print("manifest updated")
                    return 0
        print("error: could not find InstallerSha256 line", file=sys.stderr)
        return 1

    content = content.replace(PLACEHOLDER, digest)
    MANIFEST.write_text(content, encoding="utf-8")
    print(f"patched {MANIFEST.name} with {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

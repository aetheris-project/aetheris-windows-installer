"""Self-update support for the Aetheris Windows Installer.

The installer can update itself from the GitHub Releases feed of
aetheris-project/aetheris-windows-installer. On Windows a running
executable cannot be overwritten in place, so the replacement is delegated
to a detached PowerShell helper that waits for the wizard to exit, swaps
the binary and relaunches it with the original arguments.

All network operations are best-effort: a failed update check or download
reports the problem instead of breaking the wizard.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .runner import ActionStep, CommandResult

REPO = "aetheris-project/aetheris-windows-installer"
RELEASES_API = f"https://api.github.com/repos/{REPO}/releases/latest"
ASSET_NAME = "aetheris-windows-installer.exe"

TEMP_EXE_PREFIX = "aetheris-installer-"
HELPER_PREFIX = "aetheris-update-"


@dataclass(frozen=True)
class UpdateInfo:
    """Details of the latest release, when it is newer than the running build."""

    version: str
    asset_url: str
    browser_url: str
    notes: str

    @property
    def is_newer(self) -> bool:
        return _version_key(self.version) > _version_key(__version__)


def _version_key(version: str) -> tuple[int, ...]:
    """Parse 'v1.2.3' or '1.2.3' into a comparable tuple of integers."""
    parts: list[int] = []
    for token in str(version).strip().lstrip("v").split("."):
        digits = "".join(ch for ch in token if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


def check_for_update(timeout: float = 8.0) -> UpdateInfo | None:
    """Return UpdateInfo when a newer release exists, otherwise None.

    Network errors, malformed payloads and missing assets all return None:
    the wizard must never fail because the update feed is unreachable.
    """
    try:
        with urllib.request.urlopen(RELEASES_API, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - best effort by design
        return None
    tag = str(payload.get("tag_name", "")).lstrip("v")
    if not tag:
        return None
    asset_url = next(
        (a.get("browser_download_url") for a in payload.get("assets") or [] if a.get("name") == ASSET_NAME),
        None,
    )
    if not asset_url:
        return None
    info = UpdateInfo(
        version=tag,
        asset_url=asset_url,
        browser_url=str(payload.get("html_url", "")),
        notes=str(payload.get("body", "") or ""),
    )
    return info if info.is_newer else None


def download_asset(url: str, target: Path, timeout: float = 180.0) -> None:
    """Stream the release asset into target, overwriting it if present."""
    with urllib.request.urlopen(url, timeout=timeout) as resp, open(target, "wb") as out:
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            out.write(chunk)


def _powershell_helper(current: Path, new: Path, relaunch_args: list[str]) -> str:
    """Body of the detached updater script that swaps the binary."""
    lines = [
        "$ErrorActionPreference = 'Stop'",
        "Start-Sleep -Seconds 3",
        "try {",
        f"  Copy-Item -Force -LiteralPath '{new}' -LiteralPath '{current}'",
        f"  Remove-Item -Force -LiteralPath '{new}'",
    ]
    if relaunch_args:
        quoted = " ".join(f"'{arg}'" for arg in relaunch_args)
        lines.append(f"  Start-Process -FilePath '{current}' -ArgumentList {quoted}")
    else:
        lines.append(f"  Start-Process -FilePath '{current}'")
    lines.extend(["  exit 0", "} catch {", "  Write-Error $_.Exception.Message", "  exit 1", "}"])
    return "\n".join(lines) + "\n"


def apply_update(new_exe: Path, *, relaunch_args: list[str] | None = None) -> tuple[bool, str]:
    """Schedule the swap of the running executable and a relaunch.

    Returns (ok, message). When running from source (no PyInstaller) the
    update cannot be applied in place and the caller is told how to proceed.
    """
    if not getattr(sys, "frozen", False):  # pragma: no cover - only in a built exe
        return False, "Running from source: pull the repository instead of self-updating."
    current = Path(sys.executable)
    if new_exe.resolve() == current.resolve():
        return False, "The downloaded file is the running executable."
    relaunch_args = relaunch_args if relaunch_args is not None else (sys.argv[1:] if len(sys.argv) > 1 else [])
    helper = Path(tempfile.gettempdir()) / f"{HELPER_PREFIX}{__version__}-{Path(sys.argv[0]).stem}.ps1"
    helper.write_text(_powershell_helper(current, new_exe, relaunch_args), encoding="utf-8")
    try:
        subprocess.Popen(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-File",
                str(helper),
            ],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:  # pragma: no cover - platform dependent
        return False, f"Could not start the updater helper: {exc}"
    return True, "Update scheduled - the installer will close and relaunch automatically."


def run_update(*, dry_run: bool = False, quiet: bool = False, progress=None) -> list[ActionStep]:
    """Check, download and apply the latest installer release.

    Returns ActionSteps so the TUI run screen and the CLI share one
    reporting path. Dry runs report the commands without touching the
    network or the filesystem.
    """
    if dry_run:
        return [
            ActionStep(
                name="update-check",
                result=CommandResult(ok=True, returncode=0, output="[dry-run] would query the GitHub Releases feed"),
            ),
            ActionStep(
                name="update-download",
                result=CommandResult(ok=True, returncode=0, output="[dry-run] would download the new executable"),
            ),
            ActionStep(
                name="update-apply",
                result=CommandResult(ok=True, returncode=0, output="[dry-run] would swap the executable and relaunch"),
            ),
        ]

    if progress:
        progress("Checking for a newer installer release...")
    info = check_for_update()
    if info is None:
        return [
            ActionStep(
                name="update-check",
                result=CommandResult(ok=True, returncode=0, output=f"You are running the latest version (v{__version__})."),
            )
        ]
    if progress:
        progress(f"Downloading Aetheris Windows Installer v{info.version}...")
    target = Path(tempfile.gettempdir()) / f"{TEMP_EXE_PREFIX}{info.version}.exe"
    try:
        download_asset(info.asset_url, target)
    except Exception as exc:  # noqa: BLE001 - report the network failure
        return [
            ActionStep(
                name="update-download",
                result=CommandResult(ok=False, returncode=-1, output=f"Download failed: {exc}"),
            )
        ]
    if progress:
        progress("Applying the update...")
    applied, message = apply_update(target)
    return [
        ActionStep(name="update-download", result=CommandResult(ok=True, returncode=0, output=f"Downloaded v{info.version} ({target.name})")),
        ActionStep(name="update-apply", result=CommandResult(ok=applied, returncode=0 if applied else -1, output=message)),
    ]

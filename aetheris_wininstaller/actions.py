"""High-level install / uninstall actions.

Every action returns a list of (step_name, CommandResult) pairs so the TUI
progress screen and the non-interactive CLI share the same code path.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .deps import Dependency
from .envfile import write_env_file
from .paths import APP_REPO_URL, InstallPaths, is_docker_installed
from .runner import CommandResult, run_command

WINGET_BASE = ["winget", "install", "--exact", "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"]


@dataclass
class ActionStep:
    name: str
    result: CommandResult


def _winget_install(dep: Dependency, *, dry_run: bool, quiet: bool = False) -> CommandResult:
    return run_command([*WINGET_BASE, "--id", dep.winget_id], dry_run=dry_run, quiet=quiet)


def _winget_is_installed(dep: Dependency, *, dry_run: bool) -> bool:
    if dry_run:
        return False
    result = run_command(["winget", "list", "--exact", "--id", dep.winget_id], quiet=True)
    return result.returncode == 0


def install_dependencies(
    deps: list[Dependency],
    *,
    dry_run: bool = False,
    quiet: bool = False,
    progress=None,
) -> list[ActionStep]:
    """Install the given dependencies via winget."""
    steps: list[ActionStep] = []
    for dep in deps:
        if _winget_is_installed(dep, dry_run=dry_run):
            result = CommandResult(ok=True, returncode=0, output=f"{dep.winget_id} is already installed")
        else:
            if progress:
                progress(f"Installing {dep.label} ({dep.winget_id})...")
            result = _winget_install(dep, dry_run=dry_run, quiet=quiet)
        steps.append(ActionStep(name=f"dependency:{dep.winget_id}", result=result))
        if not result.ok:
            break
    return steps


def ensure_docker_ready(*, dry_run: bool = False, quiet: bool = False) -> CommandResult:
    """Verify the Docker engine is reachable; gives the user a hint otherwise."""
    if dry_run:
        return CommandResult(ok=True, returncode=0, output="[dry-run] docker not checked")
    if not is_docker_installed():
        return CommandResult(
            ok=False,
            returncode=-1,
            output="docker.exe was not found on PATH. Install Docker Desktop and start it, then re-run.",
        )
    probe = run_command(["docker", "info", "--format", "{{.ServerVersion}}"], quiet=quiet)
    return probe


def _clone_or_update_app(paths: InstallPaths, *, dry_run: bool, quiet: bool = False) -> CommandResult:
    if paths.app.exists():
        return run_command(["git", "-C", str(paths.app), "pull", "--ff-only"], dry_run=dry_run, quiet=quiet)
    return run_command(
        ["git", "clone", "--depth", "1", APP_REPO_URL, str(paths.app)],
        dry_run=dry_run,
        quiet=quiet,
    )


def _compose_up(paths: InstallPaths, *, dry_run: bool, quiet: bool = False) -> CommandResult:
    if not dry_run:
        write_env_file(paths.env_file)
    return run_command(
        ["docker", "compose", "-f", str(paths.compose_file), "up", "-d", "--build"],
        cwd=str(paths.app),
        dry_run=dry_run,
        quiet=quiet,
    )


def install_software(*, dry_run: bool = False, quiet: bool = False, progress=None) -> list[ActionStep]:
    """Clone the app repo and bring up the full Docker stack."""
    paths = InstallPaths.default()
    steps: list[ActionStep] = []

    if progress:
        progress("Checking Docker engine...")
    docker_ready = ensure_docker_ready(dry_run=dry_run, quiet=quiet)
    steps.append(ActionStep(name="docker-ready", result=docker_ready))
    if not docker_ready.ok:
        return steps

    if progress:
        progress("Fetching the aetheris-app repository...")
    clone = _clone_or_update_app(paths, dry_run=dry_run, quiet=quiet)
    steps.append(ActionStep(name="clone-app", result=clone))
    if not clone.ok:
        return steps

    if progress:
        progress("Starting the Docker stack (web, worker, backend, postgres, redis)...")
    up = _compose_up(paths, dry_run=dry_run, quiet=quiet)
    steps.append(ActionStep(name="compose-up", result=up))
    return steps


def uninstall_software(*, dry_run: bool = False, quiet: bool = False, progress=None) -> list[ActionStep]:
    """Tear down the stack and remove the app directory."""
    paths = InstallPaths.default()
    steps: list[ActionStep] = []

    if paths.compose_file.exists():
        if progress:
            progress("Stopping containers and removing volumes...")
        down = run_command(
            ["docker", "compose", "-f", str(paths.compose_file), "down", "-v", "--remove-orphans"],
            cwd=str(paths.app),
            dry_run=dry_run,
            quiet=quiet,
        )
        steps.append(ActionStep(name="compose-down", result=down))
    else:
        steps.append(
            ActionStep(
                name="compose-down",
                result=CommandResult(ok=True, returncode=0, output="No compose file found; nothing to stop"),
            )
        )

    if paths.app.exists():
        if progress:
            progress("Removing the application directory...")
        try:
            if dry_run:
                steps.append(ActionStep(name="remove-dir", result=CommandResult(ok=True, returncode=0, output=f"[dry-run] would remove {paths.app}")))
            else:
                shutil.rmtree(paths.app)
                steps.append(ActionStep(name="remove-dir", result=CommandResult(ok=True, returncode=0, output=f"Removed {paths.app}")))
        except OSError as exc:
            steps.append(ActionStep(name="remove-dir", result=CommandResult(ok=False, returncode=-1, output=str(exc))))
    else:
        steps.append(
            ActionStep(
                name="remove-dir",
                result=CommandResult(ok=True, returncode=0, output="No application directory found; nothing to remove"),
            )
        )
    return steps


def run_action(
    action: str,
    *,
    deps: list[Dependency] | None = None,
    dry_run: bool = False,
    quiet: bool = False,
    progress=None,
) -> list[ActionStep]:
    """Dispatch to the requested action. Returns the executed steps."""
    if action == "deps":
        return install_dependencies(deps or [], dry_run=dry_run, quiet=quiet, progress=progress)
    if action == "software":
        return install_software(dry_run=dry_run, quiet=quiet, progress=progress)
    if action == "both":
        dependency_steps = install_dependencies(deps or [], dry_run=dry_run, quiet=quiet, progress=progress)
        if any(not step.result.ok for step in dependency_steps):
            return dependency_steps
        return dependency_steps + install_software(dry_run=dry_run, quiet=quiet, progress=progress)
    if action == "uninstall":
        return uninstall_software(dry_run=dry_run, quiet=quiet, progress=progress)
    raise ValueError(f"unknown action: {action}")

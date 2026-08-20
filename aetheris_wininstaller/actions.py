"""High-level install / uninstall actions.

Every action returns a list of (step_name, CommandResult) pairs so the TUI
progress screen and the non-interactive CLI share the same code path.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from .deps import Dependency
from .envfile import write_env_file
from .options import InstallOptions
from .paths import APP_REPO_URL, InstallPaths, detect_db_mode, is_docker_installed
from .runner import ActionStep, CommandResult, run_command

WINGET_BASE = ["winget", "install", "--exact", "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"]


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


def _compose_up(paths: InstallPaths, options: InstallOptions, *, dry_run: bool, quiet: bool = False) -> CommandResult:
    if not dry_run:
        write_env_file(
            paths.env_file,
            db_mode=options.db_mode,
            env_timing=options.env_timing,
        )
    compose_file = paths.compose_for(options.db_mode)
    return run_command(
        ["docker", "compose", "-f", str(compose_file), "up", "-d", "--build"],
        cwd=str(paths.app),
        dry_run=dry_run,
        quiet=quiet,
    )


def install_software(
    options: InstallOptions | None = None,
    *,
    dry_run: bool = False,
    quiet: bool = False,
    progress=None,
) -> list[ActionStep]:
    """Clone the app repo and bring up the Docker stack."""
    options = options or InstallOptions()
    paths = InstallPaths.default(options.resolved_base())
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

    engine = "sqlite (local .db file)" if options.is_sqlite else "postgres"
    if progress:
        progress(f"Starting the Docker stack (web, worker, backend, redis, {engine})...")
    up = _compose_up(paths, options, dry_run=dry_run, quiet=quiet)
    steps.append(ActionStep(name="compose-up", result=up))

    if options.env_timing == "later" and up.ok:
        steps.append(
            ActionStep(
                name="env-hint",
                result=CommandResult(
                    ok=True,
                    returncode=0,
                    output=(
                        f"The stack is running with defaults. Create {paths.env_file} "
                        "manually (see the repo .env.example), then restart the stack "
                        "before configuring the platform."
                    ),
                ),
            )
        )
    return steps


def _resolve_compose(paths: InstallPaths, options: InstallOptions) -> Path:
    """Pick the compose file for management commands.

    Prefers the engine recorded in the installed .env (the installer writes
    AETHERIS_DB_MODE) so `start`/`stop`/`logs` always target the compose
    file the stack was actually brought up with.
    """
    db_mode = detect_db_mode(paths.env_file) or options.db_mode
    return paths.compose_for(db_mode)


def stack_status(
    options: InstallOptions | None = None,
    *,
    dry_run: bool = False,
    quiet: bool = False,
    progress=None,
) -> list[ActionStep]:
    """Show the running state of every stack container (docker compose ps)."""
    options = options or InstallOptions()
    paths = InstallPaths.default(options.resolved_base())
    compose_file = _resolve_compose(paths, options)
    if not compose_file.exists() and not dry_run:
        return [
            ActionStep(
                name="stack-status",
                result=CommandResult(
                    ok=False,
                    returncode=-1,
                    output=(
                        "Aetheris is not installed yet: no compose file found at "
                        f"{compose_file}. Install the software stack first."
                    ),
                ),
            )
        ]
    if progress:
        progress("Querying stack status...")
    ps = run_command(
        ["docker", "compose", "-f", str(compose_file), "ps"],
        cwd=str(paths.app),
        dry_run=dry_run,
        quiet=quiet,
    )
    return [ActionStep(name="stack-status", result=ps)]


def start_stack(
    options: InstallOptions | None = None,
    *,
    dry_run: bool = False,
    quiet: bool = False,
    progress=None,
) -> list[ActionStep]:
    """Bring the Aetheris stack up (docker compose up -d)."""
    options = options or InstallOptions()
    paths = InstallPaths.default(options.resolved_base())
    compose_file = _resolve_compose(paths, options)
    if not compose_file.exists() and not dry_run:
        return [
            ActionStep(
                name="stack-start",
                result=CommandResult(
                    ok=False,
                    returncode=-1,
                    output=(
                        "Aetheris is not installed yet: no compose file found at "
                        f"{compose_file}. Install the software stack first."
                    ),
                ),
            )
        ]
    if progress:
        progress("Starting the Aetheris stack...")
    up = run_command(
        ["docker", "compose", "-f", str(compose_file), "up", "-d"],
        cwd=str(paths.app),
        dry_run=dry_run,
        quiet=quiet,
    )
    return [ActionStep(name="stack-start", result=up)]


def stop_stack(
    options: InstallOptions | None = None,
    *,
    dry_run: bool = False,
    quiet: bool = False,
    progress=None,
) -> list[ActionStep]:
    """Stop every stack container (docker compose stop).

    Containers and volumes are kept, so the next `start` is fast.
    """
    options = options or InstallOptions()
    paths = InstallPaths.default(options.resolved_base())
    compose_file = _resolve_compose(paths, options)
    if not compose_file.exists() and not dry_run:
        return [
            ActionStep(
                name="stack-stop",
                result=CommandResult(
                    ok=False,
                    returncode=-1,
                    output=(
                        "Aetheris is not installed yet: no compose file found at "
                        f"{compose_file}. Install the software stack first."
                    ),
                ),
            )
        ]
    if progress:
        progress("Stopping the Aetheris stack...")
    stop = run_command(
        ["docker", "compose", "-f", str(compose_file), "stop"],
        cwd=str(paths.app),
        dry_run=dry_run,
        quiet=quiet,
    )
    return [ActionStep(name="stack-stop", result=stop)]


def update_stack(
    options: InstallOptions | None = None,
    *,
    dry_run: bool = False,
    quiet: bool = False,
    progress=None,
) -> list[ActionStep]:
    """Update the Aetheris software to the latest container images.

    Runs `docker compose pull` followed by `docker compose up -d`, so
    containers are recreated with the new images while volumes and data are
    kept. Always confirm with the user before calling this (the TUI and CLI
    both require explicit confirmation).
    """
    options = options or InstallOptions()
    paths = InstallPaths.default(options.resolved_base())
    compose_file = _resolve_compose(paths, options)
    if not compose_file.exists() and not dry_run:
        return [
            ActionStep(
                name="stack-update",
                result=CommandResult(
                    ok=False,
                    returncode=-1,
                    output=(
                        "Aetheris is not installed yet: no compose file found at "
                        f"{compose_file}. Install the software stack first."
                    ),
                ),
            )
        ]
    if progress:
        progress("Pulling the latest container images...")
    pull = run_command(
        ["docker", "compose", "-f", str(compose_file), "pull"],
        cwd=str(paths.app),
        dry_run=dry_run,
        quiet=quiet,
    )
    pull_step = ActionStep(name="stack-update-pull", result=pull)
    if not pull.ok:
        return [pull_step]
    if progress:
        progress("Recreating containers with the updated images...")
    up = run_command(
        ["docker", "compose", "-f", str(compose_file), "up", "-d"],
        cwd=str(paths.app),
        dry_run=dry_run,
        quiet=quiet,
    )
    return [pull_step, ActionStep(name="stack-update", result=up)]


def stack_logs(
    options: InstallOptions | None = None,
    *,
    tail: int = 200,
    dry_run: bool = False,
    quiet: bool = False,
    progress=None,
) -> list[ActionStep]:
    """Print the last `tail` lines of the whole stack (one-shot).

    The TUI live console uses :func:`runner.stream_command` with `-f`
    instead; this non-interactive variant powers the --logs CLI flag.
    """
    options = options or InstallOptions()
    paths = InstallPaths.default(options.resolved_base())
    compose_file = _resolve_compose(paths, options)
    if not compose_file.exists() and not dry_run:
        return [
            ActionStep(
                name="stack-logs",
                result=CommandResult(
                    ok=False,
                    returncode=-1,
                    output=(
                        "Aetheris is not installed yet: no compose file found at "
                        f"{compose_file}. Install the software stack first."
                    ),
                ),
            )
        ]
    if progress:
        progress(f"Fetching the last {tail} log lines...")
    logs = run_command(
        ["docker", "compose", "-f", str(compose_file), "logs", f"--tail={tail}", "--timestamps"],
        cwd=str(paths.app),
        dry_run=dry_run,
        quiet=quiet,
    )
    return [ActionStep(name="stack-logs", result=logs)]


def uninstall_software(
    options: InstallOptions | None = None,
    *,
    dry_run: bool = False,
    quiet: bool = False,
    progress=None,
) -> list[ActionStep]:
    """Tear down the stack and remove the app directory."""
    options = options or InstallOptions()
    paths = InstallPaths.default(options.resolved_base())
    steps: list[ActionStep] = []

    # Target the engine the stack was actually installed with: the .env the
    # installer wrote records it, so uninstalling an SQLite install does not
    # accidentally point at the PostgreSQL compose file.
    db_mode = detect_db_mode(paths.env_file) or options.db_mode
    compose_file = paths.compose_for(db_mode)
    if not compose_file.exists():
        # Fall back to whichever compose file is present (engine mismatch);
        # dry-run still emits the compose-down command either way.
        alternate = paths.compose_sqlite_file if db_mode == "postgres" else paths.compose_file
        if alternate.exists():
            compose_file = alternate
    if dry_run or compose_file.exists():
        if progress:
            progress("Stopping containers and removing volumes...")
        down = run_command(
            ["docker", "compose", "-f", str(compose_file), "down", "-v", "--remove-orphans"],
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
    options: InstallOptions | None = None,
    dry_run: bool = False,
    quiet: bool = False,
    progress=None,
) -> list[ActionStep]:
    """Dispatch to the requested action. Returns the executed steps."""
    if action == "deps":
        return install_dependencies(deps or [], dry_run=dry_run, quiet=quiet, progress=progress)
    if action == "software":
        return install_software(options, dry_run=dry_run, quiet=quiet, progress=progress)
    if action == "both":
        dependency_steps = install_dependencies(deps or [], dry_run=dry_run, quiet=quiet, progress=progress)
        if any(not step.result.ok for step in dependency_steps):
            return dependency_steps
        return dependency_steps + install_software(options, dry_run=dry_run, quiet=quiet, progress=progress)
    if action == "uninstall":
        return uninstall_software(options, dry_run=dry_run, quiet=quiet, progress=progress)
    if action == "status":
        return stack_status(options, dry_run=dry_run, quiet=quiet, progress=progress)
    if action == "start":
        return start_stack(options, dry_run=dry_run, quiet=quiet, progress=progress)
    if action == "stop":
        return stop_stack(options, dry_run=dry_run, quiet=quiet, progress=progress)
    if action == "logs":
        return stack_logs(options, dry_run=dry_run, quiet=quiet, progress=progress)
    if action == "update-stack":
        return update_stack(options, dry_run=dry_run, quiet=quiet, progress=progress)
    if action == "update-installer":
        # Lazy import: updater uses runner.ActionStep and would otherwise
        # create an import cycle (actions -> updater -> actions).
        from .updater import run_update

        return run_update(dry_run=dry_run, quiet=quiet, progress=progress)
    raise ValueError(f"unknown action: {action}")

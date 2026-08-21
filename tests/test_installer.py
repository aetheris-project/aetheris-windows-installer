"""Unit tests for the aetheris-windows-installer package.

All tests are platform-independent: they exercise pure logic and dry-run
paths only, never real winget / docker / git calls.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the package importable when tests run from the repo root.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aetheris_wininstaller.actions import (  # noqa: E402
    ActionStep,
    install_dependencies,
    install_software,
    run_action,
    uninstall_software,
)
from aetheris_wininstaller.deps import DEPENDENCIES, dependency_by_id  # noqa: E402
from aetheris_wininstaller.envfile import generate_secret, write_env_file  # noqa: E402
from aetheris_wininstaller.options import (  # noqa: E402
    DB_POSTGRES,
    DB_SQLITE,
    ENV_TIMING_LATER,
    ENV_TIMING_NOW,
    InstallOptions,
)
from aetheris_wininstaller.runner import CommandResult, run_command  # noqa: E402


class TestDependencies:
    def test_catalog_is_nonempty(self) -> None:
        assert len(DEPENDENCIES) >= 3

    def test_required_deps_are_first_class(self) -> None:
        required = [d for d in DEPENDENCIES if d.required]
        assert {d.winget_id for d in required} == {"Docker.DockerDesktop", "Git.Git"}

    def test_unique_winget_ids(self) -> None:
        ids = [d.winget_id for d in DEPENDENCIES]
        assert len(ids) == len(set(ids))

    def test_dependency_by_id(self) -> None:
        assert dependency_by_id("Git.Git").label == "Git for Windows"
        assert dependency_by_id("does.not.Exist") is None


class TestEnvFile:
    def test_secret_generation(self, tmp_path: Path) -> None:
        a = generate_secret()
        b = generate_secret()
        assert a and b and a != b
        assert len(a) >= 32

    def test_write_env_file_creates_file(self, tmp_path: Path) -> None:
        target = tmp_path / ".env"
        write_env_file(target)
        content = target.read_text(encoding="utf-8")
        assert "AETHERIS_SECRET=" in content
        assert "POSTGRES_PASSWORD=" in content
        assert "AETHERIS_APP_URL=http://localhost:3000" in content

    def test_write_env_file_never_overwrites(self, tmp_path: Path) -> None:
        target = tmp_path / ".env"
        target.write_text("AETHERIS_SECRET=keep-me\n", encoding="utf-8")
        write_env_file(target)
        assert "keep-me" in target.read_text(encoding="utf-8")

    def test_write_env_file_sqlite(self, tmp_path: Path) -> None:
        target = tmp_path / ".env"
        write_env_file(target, db_mode=DB_SQLITE)
        content = target.read_text(encoding="utf-8")
        assert "AETHERIS_DB_MODE=sqlite" in content
        assert "DATABASE_URL=file:/data/aetheris.db" in content
        assert "POSTGRES_PASSWORD" not in content

    def test_write_env_file_later_returns_none(self, tmp_path: Path) -> None:
        target = tmp_path / ".env"
        result = write_env_file(target, env_timing=ENV_TIMING_LATER)
        assert result is None
        assert not target.exists()


class TestActions:
    def test_install_dependencies_dry_run(self, capsys) -> None:
        steps = install_dependencies(list(DEPENDENCIES), dry_run=True)
        assert len(steps) == len(DEPENDENCIES)
        assert all(s.result.ok for s in steps)
        for step in steps:
            assert step.name.startswith("dependency:")
        captured = capsys.readouterr()
        assert "[dry-run]" in captured.out

    def test_install_software_dry_run(self, capsys) -> None:
        steps = install_software(dry_run=True)
        names = [s.name for s in steps]
        assert "docker-ready" in names
        assert "clone-app" in names
        assert "compose-up" in names
        assert all(s.result.ok for s in steps)

    def test_install_software_custom_dir_and_sqlite(self, capsys, tmp_path: Path) -> None:
        options = InstallOptions(base_dir=tmp_path, db_mode=DB_SQLITE)
        steps = install_software(options, dry_run=True)
        names = [s.name for s in steps]
        assert "clone-app" in names
        assert "compose-up" in names
        captured = capsys.readouterr()
        # The sqlite compose file is used and the directory is respected.
        assert "docker-compose.sqlite.yml" in captured.out
        assert str(tmp_path) in captured.out

    def test_install_software_env_later_adds_hint(self, capsys) -> None:
        steps = install_software(
            InstallOptions(env_timing=ENV_TIMING_LATER, db_mode=DB_SQLITE),
            dry_run=True,
        )
        names = [s.name for s in steps]
        assert "env-hint" in names

    def test_install_software_custom_dir_default(self, capsys) -> None:
        steps = install_software(dry_run=True)
        captured = capsys.readouterr()
        # Default base directory is %USERPROFILE%\aetheris.
        assert "docker-compose.yml" in captured.out

    def test_uninstall_dry_run(self) -> None:
        steps = uninstall_software(dry_run=True)
        names = [s.name for s in steps]
        assert "compose-down" in names
        assert "remove-dir" in names

    def test_uninstall_uses_sqlite_compose(self, capsys, tmp_path: Path) -> None:
        options = InstallOptions(base_dir=tmp_path, db_mode=DB_SQLITE)
        steps = uninstall_software(options, dry_run=True)
        captured = capsys.readouterr()
        assert "docker-compose.sqlite.yml" in captured.out

    def test_uninstall_detects_sqlite_from_env(self, capsys, tmp_path: Path) -> None:
        # A sqlite install is uninstalled without repeating --db sqlite: the
        # .env the installer wrote must steer the uninstall to the right
        # compose file.
        app_dir = tmp_path / "aetheris-app"
        app_dir.mkdir(parents=True)
        (app_dir / "docker-compose.sqlite.yml").write_text("services: {}\n", encoding="utf-8")
        (app_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
        (app_dir / ".env").write_text("AETHERIS_DB_MODE=sqlite\n", encoding="utf-8")

        uninstall_software(InstallOptions(base_dir=tmp_path), dry_run=True, progress=print)
        captured = capsys.readouterr()
        assert "docker-compose.sqlite.yml" in captured.out

    def test_uninstall_falls_back_to_present_compose(self, capsys, tmp_path: Path) -> None:
        # Engine mismatch (env says postgres, only the sqlite compose exists):
        # the uninstall must still tear down with whatever compose file is
        # actually present.
        app_dir = tmp_path / "aetheris-app"
        app_dir.mkdir(parents=True)
        (app_dir / "docker-compose.sqlite.yml").write_text("services: {}\n", encoding="utf-8")

        uninstall_software(InstallOptions(base_dir=tmp_path, db_mode=DB_POSTGRES), dry_run=True, progress=print)
        captured = capsys.readouterr()
        assert "docker-compose.sqlite.yml" in captured.out

    def test_run_action_dispatch(self) -> None:
        assert run_action("deps", deps=list(DEPENDENCIES), dry_run=True)[0].name.startswith("dependency:")
        assert run_action("software", dry_run=True)[0].name == "docker-ready"
        assert run_action("uninstall", dry_run=True)[0].name == "compose-down"

    def test_update_stack_dry_run(self, capsys, tmp_path: Path) -> None:
        from aetheris_wininstaller.actions import update_stack

        app_dir = tmp_path / "aetheris-app"
        app_dir.mkdir(parents=True)
        (app_dir / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")

        steps = update_stack(InstallOptions(base_dir=tmp_path), dry_run=True)
        names = [s.name for s in steps]
        assert names == ["stack-update-pull", "stack-update"]
        assert all(s.result.ok for s in steps)
        captured = capsys.readouterr()
        # docker may be invoked as a bare command or as the full Docker
        # Desktop path; both forms carry the compose subcommand.
        assert "compose" in captured.out
        assert "pull" in captured.out

    def test_update_stack_not_installed_is_a_clear_failure(self, tmp_path: Path) -> None:
        from aetheris_wininstaller.actions import update_stack

        steps = update_stack(InstallOptions(base_dir=tmp_path))
        assert len(steps) == 1
        assert steps[0].name == "stack-update"
        assert steps[0].result.ok is False
        assert "not installed yet" in steps[0].result.output

    def test_run_action_update_stack_dispatch(self, capsys) -> None:
        steps = run_action("update-stack", dry_run=True)
        assert steps[0].name == "stack-update-pull"
        captured = capsys.readouterr()
        assert "pull" in captured.out

    def test_run_action_update_installer_dry_run(self) -> None:
        steps = run_action("update-installer", dry_run=True)
        names = [s.name for s in steps]
        assert "update-check" in names
        assert "update-apply" in names
        assert all(s.result.ok for s in steps)

    def test_update_stack_uses_detected_sqlite_compose(self, capsys, tmp_path: Path) -> None:
        app_dir = tmp_path / "aetheris-app"
        app_dir.mkdir(parents=True)
        (app_dir / "docker-compose.sqlite.yml").write_text("services: {}\n", encoding="utf-8")
        (app_dir / ".env").write_text("AETHERIS_DB_MODE=sqlite\n", encoding="utf-8")

        run_action("update-stack", options=InstallOptions(base_dir=tmp_path), dry_run=True)
        captured = capsys.readouterr()
        assert "docker-compose.sqlite.yml" in captured.out

    def test_run_action_management_dispatch_dry_run(self, capsys) -> None:
        from aetheris_wininstaller.actions import stack_logs, stack_status, start_stack, stop_stack

        assert stack_status(dry_run=True)[0].name == "stack-status"
        assert start_stack(dry_run=True)[0].name == "stack-start"
        assert stop_stack(dry_run=True)[0].name == "stack-stop"
        assert stack_logs(dry_run=True)[0].name == "stack-logs"
        captured = capsys.readouterr()
        assert "compose" in captured.out
        assert "--tail=200" in captured.out

    def test_management_not_installed_is_a_clear_failure(self, tmp_path: Path) -> None:
        # Without a compose file the management commands explain that the
        # software stack must be installed first (real mode, not dry-run).
        from aetheris_wininstaller.actions import start_stack

        steps = start_stack(InstallOptions(base_dir=tmp_path))
        assert len(steps) == 1
        assert steps[0].name == "stack-start"
        assert steps[0].result.ok is False
        assert "not installed yet" in steps[0].result.output

    def test_run_action_both_chains_deps_and_software(self) -> None:
        steps = run_action("both", deps=list(DEPENDENCIES), dry_run=True)
        names = [s.name for s in steps]
        assert names[0].startswith("dependency:")
        assert "clone-app" in names
        assert "compose-up" in names

    def test_deps_install_honors_failure(self) -> None:
        # A failing winget id stops the chain. dry_run=True keeps the test
        # hermetic: the patched _winget_install ignores it and returns failure.
        from aetheris_wininstaller.actions import _winget_install
        from aetheris_wininstaller.deps import Dependency

        def patched(dep, *, dry_run, quiet=False):  # pragma: no cover - replaced below
            return CommandResult(ok=False, returncode=1, output="boom")

        import aetheris_wininstaller.actions as actions_module

        original = _winget_install
        actions_module._winget_install = patched  # type: ignore[assignment]
        try:
            steps = actions_module.install_dependencies([Dependency("X.Y", "X")], dry_run=True)
            assert len(steps) == 1
            assert steps[0].result.ok is False
        finally:
            actions_module._winget_install = original  # type: ignore[assignment]


class TestDockerDetection:
    def test_find_docker_from_path(self, monkeypatch, tmp_path: Path) -> None:
        from aetheris_wininstaller import paths

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        docker_exe = bin_dir / "docker.exe"
        docker_exe.write_text("", encoding="utf-8")
        monkeypatch.setenv("PATH", str(bin_dir))

        assert paths.find_docker() == docker_exe
        assert paths.is_docker_installed()

    def test_find_docker_from_desktop_paths(self, monkeypatch, tmp_path: Path) -> None:
        """A freshly installed Docker Desktop is found even when the process
        PATH is stale (winget updates the registry, not the running process)."""
        from aetheris_wininstaller import paths

        desktop_bin = tmp_path / "Docker" / "Docker" / "resources" / "bin"
        desktop_bin.mkdir(parents=True)
        (desktop_bin / "docker.exe").write_text("", encoding="utf-8")

        monkeypatch.setenv("PATH", str(tmp_path / "empty"))
        monkeypatch.setenv("ProgramFiles", str(tmp_path))

        assert paths.find_docker() == desktop_bin / "docker.exe"
        assert paths.is_docker_installed()

    def test_find_docker_returns_none_when_absent(self, monkeypatch, tmp_path: Path) -> None:
        from aetheris_wininstaller import paths

        monkeypatch.setenv("PATH", str(tmp_path))
        monkeypatch.setenv("ProgramFiles", str(tmp_path / "none"))
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "none2"))

        assert paths.find_docker() is None
        assert not paths.is_docker_installed()

    def test_docker_command_uses_resolved_exe(self, monkeypatch, tmp_path: Path) -> None:
        from aetheris_wininstaller import paths

        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        (bin_dir / "docker.exe").write_text("", encoding="utf-8")
        monkeypatch.setenv("PATH", str(bin_dir))

        cmd = paths.docker_command("compose", "ps")
        assert cmd[0] == str(bin_dir / "docker.exe")
        assert cmd[1:] == ["compose", "ps"]


class TestRunner:
    def test_run_command_success(self) -> None:
        result = run_command([sys.executable, "-c", "print('hello')"])
        assert result.ok
        assert "hello" in result.output

    def test_run_command_failure(self) -> None:
        result = run_command([sys.executable, "-c", "import sys; sys.exit(3)"])
        assert not result.ok
        assert result.returncode == 3

    def test_run_command_dry_run(self, capsys) -> None:
        result = run_command(["some", "command"], dry_run=True)
        assert result.ok
        captured = capsys.readouterr()
        assert "[dry-run] some command" in captured.out


class TestCliExitCodes:
    """Exit-code contract of the non-interactive CLI.

    Software-stack steps (docker-ready / compose-up) are best-effort because
    they depend on Docker Desktop having been started by the user; dependency
    failures remain fatal. This mirrors the silent winget install path.
    """

    def test_software_docker_not_ready_is_best_effort(self, monkeypatch, capsys) -> None:
        from aetheris_wininstaller import actions, cli

        fake_steps = [
            ActionStep("docker-ready", CommandResult(ok=False, returncode=-1, output="docker.exe not found")),
        ]
        monkeypatch.setattr(actions, "run_action", lambda *args, **kwargs: fake_steps)
        assert cli.main(["--software"]) == 0
        assert "Docker is not ready yet" in capsys.readouterr().out

    def test_software_dependency_failure_is_fatal(self, monkeypatch, capsys) -> None:
        from aetheris_wininstaller import actions, cli

        fake_steps = [
            ActionStep("dependency:Docker.DockerDesktop", CommandResult(ok=False, returncode=1, output="failed")),
        ]
        monkeypatch.setattr(actions, "run_action", lambda *args, **kwargs: fake_steps)
        assert cli.main(["--both"]) == 1

    def test_deps_failure_is_fatal(self, monkeypatch, capsys) -> None:
        from aetheris_wininstaller import actions, cli

        fake_steps = [
            ActionStep("dependency:Git.Git", CommandResult(ok=False, returncode=1, output="failed")),
        ]
        monkeypatch.setattr(actions, "run_action", lambda *args, **kwargs: fake_steps)
        assert cli.main(["--deps"]) == 1

    def test_management_failure_is_fatal(self, monkeypatch, capsys) -> None:
        from aetheris_wininstaller import actions, cli

        fake_steps = [
            ActionStep("stack-start", CommandResult(ok=False, returncode=1, output="docker failed")),
        ]
        monkeypatch.setattr(actions, "run_action", lambda *args, **kwargs: fake_steps)
        assert cli.main(["--start"]) == 1
        assert "The stack command failed" in capsys.readouterr().out

    def test_management_success_exits_zero(self, monkeypatch, capsys) -> None:
        from aetheris_wininstaller import actions, cli

        fake_steps = [
            ActionStep("stack-logs", CommandResult(ok=True, returncode=0, output="log line")),
        ]
        monkeypatch.setattr(actions, "run_action", lambda *args, **kwargs: fake_steps)
        assert cli.main(["--logs", "--tail", "5"]) == 0
        assert "Last log lines reported above." in capsys.readouterr().out

    def test_status_uses_detected_sqlite_compose(self, capsys, tmp_path: Path) -> None:
        from aetheris_wininstaller import cli
        from aetheris_wininstaller.actions import run_action as real_run

        app_dir = tmp_path / "aetheris-app"
        app_dir.mkdir(parents=True)
        (app_dir / "docker-compose.sqlite.yml").write_text("services: {}\n", encoding="utf-8")
        (app_dir / ".env").write_text("AETHERIS_DB_MODE=sqlite\n", encoding="utf-8")

        # --status --dry-run must resolve the sqlite compose file from the .env.
        assert cli.main(["--status", "--dry-run", "--dir", str(tmp_path)]) == 0
        captured = capsys.readouterr()
        assert "docker-compose.sqlite.yml" in captured.out

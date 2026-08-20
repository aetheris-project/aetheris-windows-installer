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

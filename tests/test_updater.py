"""Tests for the self-update machinery (no network access)."""

from __future__ import annotations

import json
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aetheris_wininstaller import __version__  # noqa: E402
from aetheris_wininstaller.updater import (  # noqa: E402
    UpdateInfo,
    _version_key,
    apply_update,
    check_for_update,
    run_update,
)


class TestVersionKey:
    def test_plain_semver(self) -> None:
        assert _version_key("1.2.3") == (1, 2, 3)

    def test_v_prefix(self) -> None:
        assert _version_key("v1.2.3") == (1, 2, 3)

    def test_ordering(self) -> None:
        assert _version_key("1.10.0") > _version_key("1.9.9")
        assert _version_key("2.0.0") > _version_key("1.99.99")

    def test_prerelease_suffix_does_not_break_parsing(self) -> None:
        # Prerelease tokens never crash the parser; digit parts still compare.
        assert _version_key("1.2.3-beta.1") == (1, 2, 3, 1)
        assert _version_key("1.2.3-beta.1") < _version_key("1.2.4")


class TestUpdateInfo:
    def test_is_newer(self) -> None:
        newer = UpdateInfo(version="99.0.0", asset_url="u", browser_url="b", notes="n")
        assert newer.is_newer

    def test_same_version_is_not_newer(self) -> None:
        same = UpdateInfo(version=__version__, asset_url="u", browser_url="b", notes="n")
        assert not same.is_newer


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def read(self) -> bytes:
        return self._payload


def _install_fake_release(monkeypatch, payload: dict) -> None:
    monkeypatch.setattr(
        urllib.request,
        "urlopen",
        lambda url, timeout=0: _FakeResponse(payload),
    )


class TestCheckForUpdate:
    def test_newer_release_is_reported(self, monkeypatch) -> None:
        _install_fake_release(
            monkeypatch,
            {
                "tag_name": "v9.9.9",
                "html_url": "https://github.com/aetheris-project/aetheris-windows-installer/releases/tag/v9.9.9",
                "body": "release notes",
                "assets": [
                    {"name": "aetheris-windows-installer.exe", "browser_download_url": "https://example.com/exe"}
                ],
            },
        )
        info = check_for_update()
        assert info is not None
        assert info.version == "9.9.9"
        assert info.asset_url == "https://example.com/exe"
        assert "9.9.9" in info.browser_url

    def test_current_version_returns_none(self, monkeypatch) -> None:
        _install_fake_release(
            monkeypatch,
            {
                "tag_name": f"v{__version__}",
                "html_url": "https://example.com",
                "assets": [{"name": "aetheris-windows-installer.exe", "browser_download_url": "https://example.com/exe"}],
            },
        )
        assert check_for_update() is None

    def test_missing_asset_returns_none(self, monkeypatch) -> None:
        _install_fake_release(
            monkeypatch,
            {"tag_name": "v9.9.9", "html_url": "https://example.com", "assets": []},
        )
        assert check_for_update() is None

    def test_network_error_returns_none(self, monkeypatch) -> None:
        def boom(url, timeout=0):  # pragma: no cover - replaced below
            raise OSError("network down")

        monkeypatch.setattr(urllib.request, "urlopen", boom)
        assert check_for_update() is None


class TestRunUpdate:
    def test_dry_run_never_touches_network(self, monkeypatch, capsys) -> None:
        def boom(url, timeout=0):  # pragma: no cover - must not be called
            raise AssertionError("dry-run must not hit the network")

        monkeypatch.setattr(urllib.request, "urlopen", boom)
        steps = run_update(dry_run=True, progress=print)
        names = [s.name for s in steps]
        assert names == ["update-check", "update-download", "update-apply"]
        assert all(s.result.ok for s in steps)

    def test_source_run_cannot_apply(self, monkeypatch, tmp_path: Path) -> None:
        # Not frozen (tests run from source): apply_update must refuse to
        # swap python.exe with the downloaded file.
        ok, message = apply_update(tmp_path / "new.exe")
        assert ok is False
        assert "source" in message.lower() or "Running from source" in message


class TestApplyUpdateHelper:
    def test_helper_script_content(self) -> None:
        from aetheris_wininstaller.updater import _powershell_helper

        script = _powershell_helper(
            Path(r"C:\Users\test\aetheris-windows-installer.exe"),
            Path(r"C:\Temp\aetheris-installer-9.9.9.exe"),
            ["--tui"],
        )
        assert "Copy-Item -Force" in script
        assert "aetheris-installer-9.9.9.exe" in script
        assert "Start-Process" in script
        assert "'--tui'" in script

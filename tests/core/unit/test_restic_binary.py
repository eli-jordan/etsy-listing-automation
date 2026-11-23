"""Which restic the app runs, and installing the pinned release
(workspace-backup spec, *Scope and decisions*, restic binary; plan, PR 2).

Downloads are faked: ``fetch`` writes the bytes a URL would serve. Every test
passes ``home`` under ``tmp_path`` and proves the real home is untouched
(plan, P2).
"""

from __future__ import annotations

import bz2
import hashlib
import io
import sys
import zipfile
from pathlib import Path

import pytest

from etsy_listings.core.backup.binary import (
    RESTIC_BINARY_ENV_VAR,
    RESTIC_VERSION,
    ReleaseAsset,
    ResticBinaries,
    ResticInstallError,
)
from etsy_listings.core.user_directory import user_directory

BINARY = b"#!restic 0.19.1 stand-in\n"


@pytest.fixture(autouse=True)
def real_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """What ``Path.home()`` answers, so a test can prove it stayed empty."""
    home = tmp_path / "real-home"
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.delenv(RESTIC_BINARY_ENV_VAR, raising=False)
    return home


def _zip(member: str, data: bytes) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("README.md", b"not the binary")
        archive.writestr(member, data)
    return buffer.getvalue()


def _asset(archive: bytes, *, unpack: str = "zip") -> ReleaseAsset:
    return ReleaseAsset(
        name=f"restic_{RESTIC_VERSION}_test.{unpack}",
        sha256=hashlib.sha256(archive).hexdigest(),
        member=f"restic_{RESTIC_VERSION}_test.exe",
        unpack=unpack,  # type: ignore[arg-type]  # -- the test names a literal the model accepts
    )


class Served:
    """A fake download: every URL serves ``archive``, and each fetch is counted."""

    def __init__(self, archive: bytes) -> None:
        self.archive = archive
        self.urls: list[str] = []

    def __call__(self, url: str, target: Path) -> None:
        self.urls.append(url)
        target.write_bytes(self.archive)


def _binaries(home: Path, archive: bytes, asset: ReleaseAsset) -> tuple[ResticBinaries, Served]:
    served = Served(archive)
    return ResticBinaries(home=home, fetch=served, asset=asset), served


def test_the_user_directory_is_under_home_and_is_not_created(tmp_path: Path) -> None:
    assert user_directory(tmp_path) == tmp_path / ".etsy-listings"
    assert not (tmp_path / ".etsy-listings").exists()


def test_the_user_directory_defaults_to_the_real_home(real_home: Path) -> None:
    assert user_directory() == real_home / ".etsy-listings"


def test_installing_unpacks_the_pinned_binary_under_the_user_directory(
    tmp_path: Path, real_home: Path
) -> None:
    archive = _zip(f"restic_{RESTIC_VERSION}_test.exe", BINARY)
    binaries, served = _binaries(tmp_path / "home", archive, _asset(archive))

    installed = binaries.install()

    assert installed.read_bytes() == BINARY
    assert installed.parent == tmp_path / "home" / ".etsy-listings" / "restic" / RESTIC_VERSION
    assert served.urls == [
        f"https://github.com/restic/restic/releases/download/v{RESTIC_VERSION}"
        f"/restic_{RESTIC_VERSION}_test.zip"
    ]
    assert [path.name for path in installed.parent.iterdir()] == [installed.name]
    assert not real_home.exists()


def test_a_bz2_release_unpacks_to_an_executable(tmp_path: Path) -> None:
    archive = bz2.compress(BINARY)
    binaries, _ = _binaries(tmp_path, archive, _asset(archive, unpack="bz2"))

    installed = binaries.install()

    assert installed.read_bytes() == BINARY
    if sys.platform != "win32":
        assert installed.stat().st_mode & 0o111


def test_a_digest_mismatch_is_refused_and_leaves_nothing_installed(
    tmp_path: Path, real_home: Path
) -> None:
    archive = _zip(f"restic_{RESTIC_VERSION}_test.exe", BINARY)
    tampered = _zip(f"restic_{RESTIC_VERSION}_test.exe", b"something else")
    binaries, _ = _binaries(tmp_path, tampered, _asset(archive))

    with pytest.raises(ResticInstallError, match="SHA-256"):
        binaries.install()

    assert binaries.installed() is None
    assert list((tmp_path / ".etsy-listings" / "restic").iterdir()) == []
    assert not real_home.exists()


def test_an_archive_without_the_binary_leaves_nothing_installed(tmp_path: Path) -> None:
    archive = _zip("restic_other.exe", BINARY)
    binaries, _ = _binaries(tmp_path, archive, _asset(archive))

    with pytest.raises(ResticInstallError, match="does not contain"):
        binaries.install()

    assert list((tmp_path / ".etsy-listings" / "restic").iterdir()) == []


def test_a_failed_download_leaves_nothing_installed(tmp_path: Path) -> None:
    def offline(url: str, target: Path) -> None:
        target.write_bytes(b"partial")
        raise OSError("connection reset")

    binaries = ResticBinaries(home=tmp_path, fetch=offline, asset=_asset(b"x"))

    with pytest.raises(ResticInstallError, match="connection reset"):
        binaries.install()

    assert list((tmp_path / ".etsy-listings" / "restic").iterdir()) == []


def test_an_installed_release_is_not_downloaded_again(tmp_path: Path) -> None:
    archive = _zip(f"restic_{RESTIC_VERSION}_test.exe", BINARY)
    binaries, served = _binaries(tmp_path, archive, _asset(archive))
    first = binaries.install()

    assert binaries.ensure(None) == first
    assert binaries.install() == first
    assert len(served.urls) == 1


def test_nothing_is_installed_until_asked(tmp_path: Path) -> None:
    archive = _zip(f"restic_{RESTIC_VERSION}_test.exe", BINARY)
    binaries, served = _binaries(tmp_path, archive, _asset(archive))

    assert binaries.locate(None) is None
    assert served.urls == []
    assert not (tmp_path / ".etsy-listings").exists()


def test_the_setting_names_another_binary(tmp_path: Path) -> None:
    own = tmp_path / "bin" / "restic"
    binaries = ResticBinaries(home=tmp_path, fetch=Served(b""), asset=_asset(b""))

    assert binaries.locate(own) == own
    assert binaries.ensure(own) == own


def test_the_environment_variable_wins_over_the_setting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The process environment overrides the workspace's files, as it does for
    credentials, which is how CI points tests at its download (plan, P3)."""
    monkeypatch.setenv(RESTIC_BINARY_ENV_VAR, str(tmp_path / "ci" / "restic"))
    binaries = ResticBinaries(home=tmp_path, fetch=Served(b""), asset=_asset(b""))

    assert binaries.locate(tmp_path / "bin" / "restic") == tmp_path / "ci" / "restic"


def test_an_unsupported_platform_is_refused_by_name(tmp_path: Path) -> None:
    with pytest.raises(ResticInstallError, match="Darwin arm64"):
        ResticBinaries(home=tmp_path, system="Darwin", machine="arm64").install()


@pytest.mark.parametrize(
    ("system", "machine", "suffix"),
    [("Windows", "AMD64", "windows_amd64.zip"), ("Linux", "x86_64", "linux_amd64.bz2")],
)
def test_each_supported_platform_downloads_its_own_release(
    tmp_path: Path, system: str, machine: str, suffix: str
) -> None:
    served = Served(b"not the pinned archive")
    binaries = ResticBinaries(home=tmp_path, fetch=served, system=system, machine=machine)

    with pytest.raises(ResticInstallError, match="SHA-256"):
        binaries.install()

    assert served.urls[0].endswith(f"/restic_{RESTIC_VERSION}_{suffix}")

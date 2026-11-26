from __future__ import annotations

import os
import platform
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from etsy_listings.core.backup import installation
from etsy_listings.core.errors import UserFacingError
from etsy_listings.core.user_directory import user_directory

RESTIC_BINARY_ENV_VAR = "ETSY_LISTINGS_RESTIC_BINARY"
"""Overrides the ``restic_binary`` setting, as the process environment
overrides the workspace's ``.env`` for credentials. Tests and CI find the
pinned binary through it (workspace-backup plan, P3)."""

RESTIC_VERSION = "0.19.1"
"""The newest restic release at least two weeks old on 2026-11-23 (spec,
*Open questions*): v0.19.1, published 2026-07-05. v0.20.0 (2026-11-19) was
too new."""

RELEASE_URL = f"https://github.com/restic/restic/releases/download/v{RESTIC_VERSION}"


class ResticInstallError(UserFacingError):
    pass


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    sha256: str
    member: str
    """The binary's name inside a zip; unused for a bz2, which holds only it."""
    unpack: Literal["zip", "bz2"]


# From the release's SHA256SUMS; the Windows zip's checked by download on 2026-11-23.
ASSETS: dict[tuple[str, str], ReleaseAsset] = {
    ("Windows", "AMD64"): ReleaseAsset(
        name=f"restic_{RESTIC_VERSION}_windows_amd64.zip",
        sha256="da948ad707ed690426473aaba2046cd61f8f90f6f0e7dab6be0d5796531de67d",
        member=f"restic_{RESTIC_VERSION}_windows_amd64.exe",
        unpack="zip",
    ),
    ("Linux", "x86_64"): ReleaseAsset(
        name=f"restic_{RESTIC_VERSION}_linux_amd64.bz2",
        sha256="f415415624dcc452f2a02b8c33641791a8c6d6d3b65bbb3543fcf9a25151585c",
        member=f"restic_{RESTIC_VERSION}_linux_amd64",
        unpack="bz2",
    ),
}

Fetch = Callable[[str, Path], None]
"""Download the URL into the file at the path."""


class ResticBinaries:
    def __init__(
        self,
        *,
        home: Path | None = None,
        fetch: Fetch | None = None,
        asset: ReleaseAsset | None = None,
        system: str | None = None,
        machine: str | None = None,
    ) -> None:
        self.root = user_directory(home) / "restic"
        self._fetch = fetch
        self._asset = asset
        self._platform = (system or platform.system(), machine or platform.machine())

    @property
    def pinned(self) -> Path:
        name = "restic.exe" if self._platform[0] == "Windows" else "restic"
        return self.root / RESTIC_VERSION / name

    def installed(self) -> Path | None:
        return self.pinned if self.pinned.is_file() else None

    def locate(self, configured: Path | None) -> Path | None:
        from_env = os.environ.get(RESTIC_BINARY_ENV_VAR)
        if from_env:
            return Path(from_env)
        if configured is not None:
            return configured
        return self.installed()

    def ensure(self, configured: Path | None) -> Path:
        return self.locate(configured) or self.install()

    def install(self) -> Path:
        existing = self.installed()
        if existing is not None:
            return existing
        asset = self._asset or self._platform_asset()
        try:
            return installation.install(
                asset,
                url=f"{RELEASE_URL}/{asset.name}",
                target=self.pinned,
                fetch=self._fetch or installation.download,
            )
        except installation.InstallationError as exc:
            raise ResticInstallError(f"Could not install restic {RESTIC_VERSION}: {exc}") from exc

    def _platform_asset(self) -> ReleaseAsset:
        asset = ASSETS.get(self._platform)
        if asset is None:
            system, machine = self._platform
            raise ResticInstallError(
                f"No pinned restic for {system} {machine}. Install restic {RESTIC_VERSION} "
                f"yourself and name it in settings.yaml as backup.restic_binary."
            )
        return asset

"""Installing the pinned restic: download, digest check, unpack, rename.

Implementation only, reached through ``binary.ResticBinaries`` (an Import
Linter contract, as for ``preparation.installation``). Mirrors
``preparation.runtime.Runtime._install``: everything happens in a staging
directory beside the target, which is renamed into place only when the
binary is complete, and removed on any failure.
"""

from __future__ import annotations

import bz2
import hashlib
import shutil
import sys
import uuid
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from etsy_listings.core.workspace.trees import remove_tree

if TYPE_CHECKING:
    from etsy_listings.core.backup.binary import ReleaseAsset

DOWNLOAD_TIMEOUT_SECONDS = 120.0


class InstallationError(Exception):
    pass


def download(url: str, target: Path) -> None:
    import httpx  # noqa: PLC0415 -- httpx loads only for an explicit install

    try:
        with (
            # GitHub redirects release files to its object store.
            httpx.stream(
                "GET", url, follow_redirects=True, timeout=DOWNLOAD_TIMEOUT_SECONDS
            ) as reply,
            target.open("wb") as stream,
        ):
            reply.raise_for_status()
            for chunk in reply.iter_bytes():
                stream.write(chunk)
    except httpx.HTTPError as exc:
        raise InstallationError(f"downloading {url} failed: {exc}") from exc


def install(
    asset: ReleaseAsset, *, url: str, target: Path, fetch: Callable[[str, Path], None]
) -> Path:
    release = target.parent
    staging = release.parent / f".staging-{uuid.uuid4().hex}"
    staging.mkdir(parents=True)
    try:
        archive = staging / asset.name
        try:
            fetch(url, archive)
        except OSError as exc:
            raise InstallationError(f"downloading {url} failed: {exc}") from exc
        _check_digest(archive, asset.sha256)
        _unpack(archive, asset, staging / target.name)
        archive.unlink()
        try:
            staging.rename(release)
        except OSError:
            if not target.is_file():
                raise
            remove_tree(staging)
    except BaseException as exc:
        _discard(staging, exc)
        raise
    return target


def _check_digest(archive: Path, expected: str) -> None:
    with archive.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != expected:
        raise InstallationError(
            f"{archive.name} has SHA-256 {actual}, not the pinned {expected}. "
            "Nothing was installed."
        )


def _unpack(archive: Path, asset: ReleaseAsset, binary: Path) -> None:
    with binary.open("wb") as out:
        if asset.unpack == "bz2":
            with bz2.open(archive, "rb") as source:
                shutil.copyfileobj(source, out)
        else:
            with zipfile.ZipFile(archive) as bundle:
                if asset.member not in bundle.namelist():
                    raise InstallationError(f"{archive.name} does not contain {asset.member}")
                with bundle.open(asset.member) as source:
                    shutil.copyfileobj(source, out)
    if sys.platform != "win32":
        binary.chmod(0o755)


def _discard(staging: Path, failure: BaseException) -> None:
    if not staging.exists():
        return
    try:
        remove_tree(staging)
    except OSError as cleanup:
        failure.add_note(f"Unfinished restic install remains for cleanup: {staging}: {cleanup}")

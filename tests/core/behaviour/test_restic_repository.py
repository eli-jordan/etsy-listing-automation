"""restic itself, against a repository in ``tmp_path`` (workspace-backup plan,
PR 2 and P3). Skipped unless ``ETSY_LISTINGS_RESTIC_BINARY`` names restic."""

from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from etsy_listings.core.backup.restic import (
    RepositoryLockedError,
    RepositoryNotFoundError,
    Restic,
    ResticError,
    WrongPasswordError,
)

pytestmark = pytest.mark.restic

PASSWORD = "correct horse battery staple"


@pytest.fixture
def restic(restic_binary: Path, tmp_path: Path) -> Restic:
    return Restic(restic_binary, tmp_path / "repository", PASSWORD)


def test_init_creates_a_repository_with_no_snapshots(restic: Restic) -> None:
    assert len(restic.init()) == 64
    assert (restic.repository / "config").is_file()
    assert restic.snapshots() == ()


def test_a_second_init_is_refused(restic: Restic) -> None:
    restic.init()

    with pytest.raises(ResticError, match="already exists"):
        restic.init()


def test_snapshots_lists_a_backup_with_its_size(restic: Restic, tmp_path: Path) -> None:
    source = tmp_path / "workspace"
    source.mkdir()
    (source / "shop.yaml").write_bytes(b"shop: naturally inked\n")
    restic.init()

    restic.run("backup", str(source), "--host", "test")
    snapshots = restic.snapshots(lock=False)

    assert len(snapshots) == 1
    assert snapshots[0].hostname == "test"
    assert (snapshots[0].files, snapshots[0].size) == (1, 22)


def test_a_folder_that_is_not_a_repository_is_reported(restic: Restic) -> None:
    restic.repository.mkdir()
    (restic.repository / "notes.txt").write_text("not restic", encoding="utf-8")

    with pytest.raises(RepositoryNotFoundError, match="repository does not exist"):
        restic.snapshots()


def test_the_wrong_password_is_reported_without_echoing_it(
    restic: Restic, restic_binary: Path
) -> None:
    restic.init()
    wrong = Restic(restic_binary, restic.repository, "not the password at all")

    with pytest.raises(WrongPasswordError) as caught:
        wrong.snapshots()

    assert "wrong password" in str(caught.value)
    assert "not the password at all" not in str(caught.value)


@pytest.fixture
def exclusive_lock(restic: Restic, restic_binary: Path) -> Iterator[None]:
    """``restic key passwd`` takes the exclusive lock, then waits on stdin for
    the new password; an open pipe keeps it waiting with the lock held."""
    restic.init()
    env = {**os.environ, "RESTIC_PASSWORD": PASSWORD}
    holder = subprocess.Popen(
        [str(restic_binary), "--repo", str(restic.repository), "key", "passwd"],
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 30
        while not any((restic.repository / "locks").iterdir()):
            assert time.monotonic() < deadline, "restic key passwd never took its lock"
            time.sleep(0.05)
        yield
    finally:
        holder.kill()
        holder.wait()


@pytest.mark.usefixtures("exclusive_lock")
def test_a_repository_locked_elsewhere_is_reported(restic: Restic) -> None:
    with pytest.raises(RepositoryLockedError, match="locked exclusively") as caught:
        restic.snapshots()

    assert caught.value.exit_code == 11

"""restic itself, against a repository in ``tmp_path`` (workspace-backup plan,
PR 2 and P3). Skipped unless ``ETSY_LISTINGS_RESTIC_BINARY`` names restic."""

from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings.core.backup.restic import (
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

"""Copying the backup storage folder to destinations, checking and repairing
them (workspace-backup spec, *Copy to destinations*, *Changed and unexpected
files*, *Checking a destination*; plan, PR 4). Repositories are fake
restic-shaped folders under ``tmp_path`` (plan, P2).
"""

from __future__ import annotations

import errno
import os
import random
import threading
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from etsy_listings.core.backup import destinations
from etsy_listings.core.backup.destinations import (
    ChangedFile,
    CopyHooks,
    CopyStep,
    DestinationNotFoundError,
    ForeignCopyError,
    check_destination,
    copy_repository,
    create_destination,
    repair_destination,
)

from tests.support.repository_files import (
    FakeRepository,
    files,
    identities,
    identity,
    missing_packs,
)


@pytest.fixture
def local(tmp_path: Path) -> FakeRepository:
    repository = FakeRepository(tmp_path / "backups")
    repository.backup("first")
    return repository


@pytest.fixture
def destination(tmp_path: Path) -> Path:
    folder = tmp_path / "icloud" / "backups"
    folder.mkdir(parents=True)
    return folder


def _prune(local: FakeRepository, *names: str) -> tuple[str, str]:
    """What a prune that repacks does: a new pack and index, then the old
    index, then the old packs, removed."""
    pack = local.pack(b"repacked")
    index = local.index(pack)
    local.remove(*names)
    return pack, index


def test_a_copy_writes_config_and_keys_then_data_then_index_then_snapshots(
    local: FakeRepository, destination: Path
) -> None:
    pack, index, snapshot = local.backup("second")
    steps: list[CopyStep] = []

    result = copy_repository(local.root, destination, hooks=CopyHooks(observe=steps.append))

    assert result.outcome == "copied"
    assert files(destination) == files(local.root)
    written = [step.name.split("/")[0] for step in steps]
    assert written == ["config", "keys", "data", "data", "index", "index", "snapshots", "snapshots"]
    assert {pack, index, snapshot} <= set(result.copied)


def test_a_damaged_local_file_stops_the_copy_before_it_reaches_the_destination(
    local: FakeRepository, destination: Path
) -> None:
    pack, index, snapshot = local.backup("second")
    (local.root / pack).write_bytes(b"pack:flipped bits")

    result = copy_repository(local.root, destination)

    assert result.outcome == "damaged"
    assert pack in (result.message or "")
    assert "damaged" in (result.message or "")
    assert not (destination / pack).exists()
    assert not (destination / index).exists()
    assert not (destination / snapshot).exists()
    assert not [name for name in files(destination) if ".copying-" in name]


def test_files_the_local_repository_dropped_are_deleted_after_copying_newest_first(
    local: FakeRepository, destination: Path
) -> None:
    old_pack, old_index, old_snapshot = local.backup("forgotten")
    copy_repository(local.root, destination)
    local.remove(old_snapshot)
    new_pack, new_index = _prune(local, old_index, old_pack)
    steps: list[CopyStep] = []
    before = identities(destination)

    result = copy_repository(local.root, destination, hooks=CopyHooks(observe=steps.append))

    assert result.outcome == "copied"
    assert files(destination) == files(local.root)
    kept = {name: file for name, file in before.items() if name not in result.deleted}
    assert {name: identities(destination)[name] for name in kept} == kept
    assert steps == [
        CopyStep("copied", new_pack),
        CopyStep("copied", new_index),
        CopyStep("deleted", old_snapshot),
        CopyStep("deleted", old_index),
        CopyStep("deleted", old_pack),
    ]
    assert result.deleted == (old_snapshot, old_index, old_pack)


def test_a_file_whose_size_changed_stops_the_copy_and_is_reported(
    local: FakeRepository, destination: Path
) -> None:
    pack, _, _ = local.backup("second")
    copy_repository(local.root, destination)
    (destination / pack).write_bytes(b"truncated")
    local.backup("third")
    before = files(destination)

    result = copy_repository(local.root, destination)

    assert result.outcome == "changed"
    size = (local.root / pack).stat().st_size
    assert result.changed == (ChangedFile(pack, expected_size=size, actual_size=9),)
    assert pack in (result.message or "")
    assert files(destination) == before


def test_config_counts_as_changed_when_any_byte_differs(
    local: FakeRepository, destination: Path
) -> None:
    copy_repository(local.root, destination)
    config = (destination / "config").read_bytes()
    (destination / "config").write_bytes(config.replace(b"2", b"3"))

    result = copy_repository(local.root, destination)

    assert result.outcome == "changed"
    assert result.changed == (ChangedFile("config", len(config), len(config)),)


@pytest.mark.parametrize("repair", [False, True])
def test_a_copy_without_config_keeps_old_backups(
    local: FakeRepository, tmp_path: Path, *, repair: bool
) -> None:
    old = FakeRepository(tmp_path / "old")
    old.backup("the only copy of the old backup")
    old.remove("config")
    before = identities(old.root)

    if repair:
        with pytest.raises(ForeignCopyError, match="config"):
            repair_destination(local.root, old.root, today=date(2026, 11, 23))
    else:
        result = copy_repository(local.root, old.root)
        assert result.outcome == "changed"
        assert "config" in (result.message or "")

    assert identities(old.root) == before


@pytest.mark.parametrize("name", ["readme.copying-0a1b2c3d", "data/a/" + "a" * 64])
def test_a_copy_keeps_non_restic_files_with_similar_names(
    local: FakeRepository, destination: Path, name: str
) -> None:
    copy_repository(local.root, destination)
    path = destination / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"keep this file")

    result = copy_repository(local.root, destination)

    assert result.unexpected == (name,)
    assert path.read_bytes() == b"keep this file"


def test_a_copy_keeps_an_expired_file_replaced_after_listing(
    local: FakeRepository, destination: Path, tmp_path: Path
) -> None:
    _, _, snapshot = local.backup("expired")
    copy_repository(local.root, destination)
    local.remove(snapshot)
    user_file = tmp_path / "replacement"
    user_file.write_bytes(b"this is someone's new file")
    target = destination / snapshot

    result = copy_repository(
        local.root, destination, hooks=CopyHooks(after_listing=lambda: user_file.replace(target))
    )

    assert result.outcome == "changed"
    assert target.read_bytes() == b"this is someone's new file"


def test_repair_sets_aside_unexpected_contents_at_an_expired_name(
    local: FakeRepository, destination: Path
) -> None:
    _, _, snapshot = local.backup("expired")
    copy_repository(local.root, destination)
    local.remove(snapshot)
    (destination / snapshot).write_bytes(b"unexpected contents")

    result = copy_repository(local.root, destination)
    assert result.unexpected == (snapshot,)
    repair = repair_destination(local.root, destination, today=date(2026, 11, 23))

    assert repair.set_aside is not None
    assert (repair.set_aside / snapshot).read_bytes() == b"unexpected contents"
    assert not (destination / snapshot).exists()


def test_a_copy_fails_safely_if_atomic_publication_is_unavailable(
    local: FakeRepository, destination: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_links(*_: object) -> None:
        raise OSError(errno.ENOTSUP, "hard links are unavailable")

    monkeypatch.setattr(
        destinations, "os", SimpleNamespace(name="posix", link=no_links, fsync=os.fsync)
    )
    result = copy_repository(local.root, destination)

    assert result.outcome == "failed"
    assert files(destination) == {}


def test_a_conflict_copy_is_reported_and_kept_while_copying_continues(
    local: FakeRepository, destination: Path
) -> None:
    pack, _, _ = local.backup("second")
    copy_repository(local.root, destination)
    conflict = f"{pack} 2"
    (destination / conflict).write_bytes(b"pack:second")
    (destination / "desktop.ini").write_bytes(b"[.ShellClassInfo]")
    new_pack, new_index, new_snapshot = local.backup("third")

    result = copy_repository(local.root, destination)

    assert result.outcome == "copied"
    assert result.unexpected == (conflict, "desktop.ini")
    assert (destination / conflict).read_bytes() == b"pack:second"
    assert (destination / "desktop.ini").is_file()
    assert set(result.copied) == {new_pack, new_index, new_snapshot}


def test_temporary_files_an_interrupted_copy_left_are_deleted(
    local: FakeRepository, destination: Path
) -> None:
    copy_repository(local.root, destination)
    pack, _, _ = local.backup("second")
    leftover = f"{pack}.copying-0a1b2c3d"
    (destination / leftover).parent.mkdir(parents=True)
    (destination / leftover).write_bytes(b"pack:sec")
    lock = destination / "locks" / ("5" * 64)
    lock.parent.mkdir(exist_ok=True)
    lock.write_bytes(b"a restore from this copy")

    result = copy_repository(local.root, destination)

    assert result.outcome == "copied"
    assert result.unexpected == ()
    assert not (destination / leftover).exists()
    assert lock.is_file()
    assert files(destination) == files(local.root) | {f"locks/{lock.name}": lock.read_bytes()}


def test_an_unreachable_destination_is_skipped_and_reported(
    local: FakeRepository, tmp_path: Path
) -> None:
    offline = tmp_path / "nas" / "backups"

    result = copy_repository(local.root, offline)

    assert result.outcome == "unreachable"
    assert str(offline) in (result.message or "")
    assert not (tmp_path / "nas").exists()


def test_a_missing_destination_folder_is_unreachable_even_when_its_parent_exists(
    local: FakeRepository, tmp_path: Path
) -> None:
    # iCloud signed out leaves iCloudDrive\ behind: creating the folder there
    # would copy everything into a folder nothing syncs.
    missing = tmp_path / "iCloudDrive" / "backups"
    missing.parent.mkdir()

    result = copy_repository(local.root, missing)

    assert result.outcome == "unreachable"
    assert "Folder not found" in (result.message or "")
    assert not missing.exists()


def test_set_up_creates_a_destination_folder_inside_an_existing_one(
    local: FakeRepository, tmp_path: Path
) -> None:
    new = tmp_path / "iCloudDrive" / "backups"
    new.parent.mkdir()

    create_destination(new)
    result = copy_repository(local.root, new)

    assert result.outcome == "copied"
    assert files(new) == files(local.root)


def test_set_up_refuses_a_destination_whose_parent_is_missing(tmp_path: Path) -> None:
    offline = tmp_path / "nas" / "backups"

    with pytest.raises(DestinationNotFoundError, match="nas"):
        create_destination(offline)

    assert not (tmp_path / "nas").exists()


def test_set_up_keeps_an_existing_destination_as_it_is(
    local: FakeRepository, destination: Path
) -> None:
    copy_repository(local.root, destination)
    before = identities(destination)

    create_destination(destination)

    assert identities(destination) == before


def test_a_prune_after_listing_never_leaves_an_index_naming_a_missing_pack(
    local: FakeRepository, destination: Path
) -> None:
    copy_repository(local.root, destination)
    [first_pack] = [name for name in files(local.root) if name.startswith("data/")]
    [first_index] = [name for name in files(local.root) if name.startswith("index/")]
    pack, index, _ = local.backup("second")

    def prune() -> None:
        _prune(local, first_index, index, first_pack, pack)

    def no_dangling_index(_: CopyStep) -> None:
        assert missing_packs(destination) == set()

    result = copy_repository(
        local.root, destination, hooks=CopyHooks(after_listing=prune, observe=no_dangling_index)
    )

    assert result.outcome == "failed"
    assert pack in (result.message or "")
    assert "next" in (result.message or "")
    assert missing_packs(destination) == set()
    assert not (destination / index).exists()


def test_a_prune_during_listing_keeps_the_previous_copy(
    local: FakeRepository, destination: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pack, index, snapshot = local.backup("expires during listing")
    copy_repository(local.root, destination)
    before = identities(destination)
    iterdir = Path.iterdir

    def list_after_prune(path: Path) -> Iterator[Path]:
        if path == local.root / "data":
            local.remove(snapshot, index, pack)
        return iterdir(path)

    monkeypatch.setattr(Path, "iterdir", list_after_prune)

    assert copy_repository(local.root, destination).outcome == "failed"
    assert identities(destination) == before


def test_a_file_that_appears_at_the_destination_mid_copy_is_never_replaced(
    local: FakeRepository, destination: Path
) -> None:
    _, _, snapshot = local.backup("second")
    target = destination / snapshot

    def someone_writes() -> None:
        target.parent.mkdir(parents=True)
        target.write_bytes(b"not restic")

    hooks = CopyHooks(after_listing=someone_writes)
    result = copy_repository(local.root, destination, hooks=hooks)

    assert result.outcome == "failed"
    assert snapshot in (result.message or "")
    assert target.read_bytes() == b"not restic"
    assert not [name for name in files(destination) if ".copying-" in name]


def test_stopping_part_way_ends_the_copy_after_the_current_file(
    local: FakeRepository, destination: Path
) -> None:
    local.backup("second")
    cancel = threading.Event()

    def stop_after_first(_: CopyStep) -> None:
        cancel.set()

    result = copy_repository(
        local.root, destination, hooks=CopyHooks(observe=stop_after_first), cancel=cancel
    )

    assert result.outcome == "stopped"
    assert result.copied == ("config",)


def test_a_file_the_sample_check_found_changed_stops_the_copy(
    local: FakeRepository, destination: Path
) -> None:
    pack, _, _ = local.backup("second")
    copy_repository(local.root, destination)
    size = (destination / pack).stat().st_size
    before = identity(destination / pack)

    result = copy_repository(local.root, destination, suspect=frozenset({pack}))

    assert result.outcome == "changed"
    assert result.changed == (ChangedFile(pack, size, size),)
    assert identity(destination / pack) == before


def _copied(local: FakeRepository, destination: Path, backups: int) -> list[str]:
    for n in range(backups):
        local.backup(f"backup {n}")
    copy_repository(local.root, destination)
    return [name for name in files(destination) if name != "config"]


def test_the_sample_check_finds_a_change_that_kept_the_size(
    local: FakeRepository, destination: Path
) -> None:
    names = _copied(local, destination, 2)
    pack = next(name for name in names if name.startswith("data/"))
    original = (destination / pack).read_bytes()
    (destination / pack).write_bytes(original[:-1] + b"!")
    before = identities(destination)

    check = check_destination(local.root, destination, fraction=1.0)

    assert check.outcome == "changed"
    assert check.changed == (ChangedFile(pack, len(original), len(original)),)
    assert pack in (check.message or "")
    assert identities(destination) == before


def test_the_sample_check_compares_config_byte_for_byte(
    local: FakeRepository, destination: Path
) -> None:
    _copied(local, destination, 1)
    config = destination / "config"
    config.write_bytes(config.read_bytes().upper())

    check = check_destination(local.root, destination, rng=random.Random(1))

    assert check.outcome == "changed"
    assert [file.name for file in check.changed] == ["config"]


def test_the_sample_check_reads_one_file_in_twenty_and_writes_nothing(
    local: FakeRepository, destination: Path
) -> None:
    names = _copied(local, destination, 12)
    before = identities(destination)

    check = check_destination(local.root, destination, rng=random.Random(7))

    assert len(names) == 40
    assert check.outcome == "ok"
    assert len(check.checked) == 2
    assert set(check.checked) <= set(names)
    assert identities(destination) == before


def test_an_unreachable_destination_is_not_checked(local: FakeRepository, tmp_path: Path) -> None:
    check = check_destination(local.root, tmp_path / "offline" / "backups")

    assert check.outcome == "unreachable"
    assert not (tmp_path / "offline").exists()


def test_repair_sets_changed_and_unexpected_files_aside_and_completes_the_copy(
    local: FakeRepository, destination: Path
) -> None:
    names = _copied(local, destination, 3)
    resized, edited = [name for name in names if name.startswith("data/")][:2]
    (destination / resized).write_bytes(b"short")
    (destination / edited).write_bytes((destination / edited).read_bytes()[:-1] + b"!")
    conflict = f"{resized} 2"
    (destination / conflict).write_bytes(b"pack:conflict")
    local.backup("after the damage")
    before = identities(destination)

    repair = repair_destination(
        local.root, destination, today=date(2026, 11, 23), suspect=frozenset({edited})
    )

    aside = destination.with_name("backups-set-aside-2026-11-23")
    assert repair.set_aside == aside
    assert repair.copy.outcome == "copied"
    assert set(repair.moved) == {resized, edited, conflict}
    assert files(destination) == files(local.root)
    for name, file in before.items():
        assert identity((aside if name in repair.moved else destination) / name) == file


def test_a_second_repair_the_same_day_never_reuses_the_set_aside_folder(
    local: FakeRepository, destination: Path
) -> None:
    _copied(local, destination, 1)
    today = date(2026, 11, 23)
    (destination / "notes.txt").write_bytes(b"first")
    first = repair_destination(local.root, destination, today=today)
    (destination / "notes.txt").write_bytes(b"second")

    second = repair_destination(local.root, destination, today=today)

    assert first.set_aside is not None
    assert second.set_aside == destination.with_name("backups-set-aside-2026-11-23-2")
    assert (first.set_aside / "notes.txt").read_bytes() == b"first"
    assert (second.set_aside / "notes.txt").read_bytes() == b"second"


def test_repairing_a_whole_copy_moves_nothing(local: FakeRepository, destination: Path) -> None:
    _copied(local, destination, 1)
    before = identities(destination)

    repair = repair_destination(local.root, destination, today=date(2026, 11, 23))

    assert (repair.set_aside, repair.moved, repair.copy.outcome) == (None, (), "copied")
    assert identities(destination) == before


def test_repair_refuses_a_copy_whose_config_differs_and_moves_nothing(
    local: FakeRepository, destination: Path
) -> None:
    """Another repository's copy, say one left from before Create a new
    repository: setting its config aside would let the copy then delete
    every pack as expired. A damaged config cannot be told apart without
    the password, so any changed config is refused (plan, PR 8)."""
    _copied(local, destination, 1)
    (destination / "config").write_bytes(b'{"version": 2, "id": "another repository"}')
    before = identities(destination)

    with pytest.raises(ForeignCopyError, match="another repository") as refused:
        repair_destination(local.root, destination, today=date(2026, 11, 23))

    assert str(destination) in str(refused.value)
    assert identities(destination) == before
    assert not destination.with_name("backups-set-aside-2026-11-23").exists()

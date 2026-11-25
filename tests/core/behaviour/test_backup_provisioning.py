"""Provisioning the backup storage folder (``backup_provisioning``): every
refusal, the one order its steps run in, and that a failure leaves the
workspace as it was. Through ``provision`` itself, as Setup, the missing
banner and ``backup init`` call it, against the in-memory restic; every
folder is under ``tmp_path`` (workspace-backup plan, P2 and P3).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from etsy_listings.core.application.backup_provisioning import (
    STAGING_MARK,
    BackupsSetUpError,
    ConnectPasswordError,
    ConnectRefusedError,
    DestinationCopy,
    DestinationHoldsRepositoryError,
    ExistingCopiesError,
    NewBlock,
    NewRepository,
    PasswordSource,
    Provisioned,
    Provisioning,
    Source,
    provision,
    source_for,
)
from etsy_listings.core.application.backup_repository import (
    SEVERAL_WORKSPACES,
    BackupOffError,
    PasswordTooShortError,
    RepositoryNotEmptyError,
    backup_settings,
)
from etsy_listings.core.application.refusals import (
    InvalidSettingsEditError,
    SettingsRevisionConflictError,
)
from etsy_listings.core.application.workspace_settings import read_settings
from etsy_listings.core.backup.binary import RESTIC_BINARY_ENV_VAR, ResticBinaries
from etsy_listings.core.backup.repository import ResticError
from etsy_listings.core.config.secrets import BACKUP_PASSWORD_VAR
from etsy_listings.core.config.settings import RetentionSettings
from etsy_listings.core.errors import RefusedError
from etsy_listings.core.workspace import layout
from etsy_listings.core.workspace.workspace import Workspace

from tests.support.backups import PASSWORD, WORKSPACE_ID, configure_backups
from tests.support.repository_files import FakeRepository, files
from tests.support.restic import InMemoryRestic, MemorySnapshot

NOW = datetime(2026, 11, 23, 9, 0, tzinfo=UTC)
OURS = "6a1f3c0e-2b9d-4e5a-8c7f-0d1e2f3a4b5c"
THEIRS = "b2c4d6e8-1a3b-4c5d-9e7f-a0b1c2d3e4f5"
HOLDS_FILES = "{} already holds files. Choose an empty or new folder."


@pytest.fixture(autouse=True)
def _no_ambient_backup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv(BACKUP_PASSWORD_VAR, raising=False)
    monkeypatch.setenv(RESTIC_BINARY_ENV_VAR, str(tmp_path / "restic"))


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    return Workspace.discover(root_override=workspace_root)


@pytest.fixture
def storage(tmp_path: Path) -> Path:
    return tmp_path / "backups"


@pytest.fixture
def restic() -> InMemoryRestic:
    fake = InMemoryRestic(lambda: NOW)
    fake.password = PASSWORD
    return fake


class _Asked:
    """A password source's ``ask`` that records each call."""

    def __init__(self, answer: str | None = PASSWORD) -> None:
        self.answer = answer
        self.sources: list[Source] = []

    def __call__(self, source: Source) -> str | None:
        self.sources.append(source)
        return self.answer


def _run(
    workspace: Workspace,
    restic: InMemoryRestic,
    asked: Provisioning,
    trying: Callable[[Path | None], None] | None = None,
) -> Provisioned:
    binaries = ResticBinaries(home=workspace.root.parent / "home")
    return provision(workspace, asked, binaries=binaries, restic=restic, trying=trying)


def _set_up(
    workspace: Workspace,
    restic: InMemoryRestic,
    storage: Path,
    source: Source | None = None,
    *,
    password: str = PASSWORD,
    destinations: tuple[Path, ...] = (),
    interval_hours: int = 12,
) -> Provisioned:
    """As Setup asks: a whole new block, the form's password."""
    asked = Provisioning(
        storage=storage,
        source=source or NewRepository(),
        password=PasswordSource.typed(password),
        new_block=NewBlock(destinations, interval_hours, RetentionSettings()),
    )
    return _run(workspace, restic, asked)


def _replace(
    workspace: Workspace,
    restic: InMemoryRestic,
    storage: Path,
    source: Source | None = None,
    *,
    ask: Callable[[Source], str | None] | None = None,
    expected_revision: str | None = None,
) -> Provisioned:
    """As the missing banner and ``backup init`` ask: the saved block, the
    stored password or else ``ask``'s."""
    asked = Provisioning(
        storage=storage,
        source=source or NewRepository(),
        password=PasswordSource.stored_or(ask or _Asked()),
        expected_revision=expected_revision,
    )
    return _run(workspace, restic, asked)


def _state(workspace: Workspace, storage: Path) -> dict[str, object]:
    """Everything a refused or failed attempt must leave as it was."""
    env = workspace.root / layout.ENV_FILE
    settings = workspace.settings_file()
    return {
        "settings": settings.read_bytes() if settings.exists() else None,
        "env": env.read_bytes() if env.exists() else None,
        "beside": sorted(path.name for path in storage.parent.iterdir()),
        "storage": files(storage) if storage.is_dir() else None,
    }


def _copy(folder: Path, *labels: str, repository_id: str = "fake") -> Path:
    """A destination copy with one backup per label."""
    copy = FakeRepository(folder, repository_id=repository_id)
    for label in labels:
        copy.backup(label)
    return copy.root


def _saved(workspace: Workspace, storage: Path, destinations: tuple[Path, ...] = ()) -> None:
    """A saved block whose repository is missing, without a stored password."""
    configure_backups(workspace.root, storage, destinations=destinations, password=None)


# ------------------------------------------------------------------ refusals


@pytest.mark.parametrize("source", ["new", "copy"])
def test_a_storage_folder_that_holds_files_is_refused_in_one_wording(
    workspace: Workspace, restic: InMemoryRestic, storage: Path, tmp_path: Path, source: str
) -> None:
    storage.mkdir()
    (storage / "holiday.jpg").write_bytes(b"mine")
    chosen = NewRepository() if source == "new" else DestinationCopy((_copy(tmp_path / "c"),))
    _saved(workspace, tmp_path / "old")
    before = _state(workspace, storage)
    asked = _Asked()

    with pytest.raises(RepositoryNotEmptyError) as refused:
        _replace(workspace, restic, storage, chosen, ask=asked)

    assert str(refused.value) == HOLDS_FILES.format(storage)
    assert asked.sources == [], "nothing is asked for an attempt already refused"
    assert restic.operations == []
    assert _state(workspace, storage) == before


def test_a_storage_folder_whose_parent_is_missing_is_refused(
    workspace: Workspace, restic: InMemoryRestic, tmp_path: Path
) -> None:
    offline = tmp_path / "offline-drive" / "backups"

    with pytest.raises(RefusedError, match="does not exist"):
        _set_up(workspace, restic, offline)

    assert not offline.parent.exists()
    assert not workspace.settings_file().exists()


@pytest.mark.parametrize("holds", ["config", "keys", "data", "snapshots", "index"])
def test_a_new_repository_is_refused_while_a_destination_holds_a_copy(
    workspace: Workspace, restic: InMemoryRestic, storage: Path, tmp_path: Path, holds: str
) -> None:
    """A new repository would leave the old copy looking changed, and a
    repair would then let the copy delete it: Connect is the way back."""
    cloud = tmp_path / "cloud"
    cloud.mkdir()
    if holds == "config":
        (cloud / "config").write_bytes(b"{}")
    else:
        (cloud / holds).mkdir()
    _saved(workspace, storage, (cloud,))
    before = _state(workspace, storage) | {"cloud": files(cloud)}

    with pytest.raises(DestinationHoldsRepositoryError) as refused:
        _replace(workspace, restic, storage)

    assert refused.value.destination == cloud
    assert "Connect" in str(refused.value)
    assert _state(workspace, storage) | {"cloud": files(cloud)} == before


def test_a_copy_that_is_not_a_repository_or_overlaps_the_folder_is_refused(
    workspace: Workspace, restic: InMemoryRestic, storage: Path, tmp_path: Path
) -> None:
    pictures = tmp_path / "pictures"
    pictures.mkdir()
    (pictures / "holiday.jpg").write_bytes(b"mine")
    cloud = _copy(tmp_path / "cloud", "first")
    _saved(workspace, storage)
    before = _state(workspace, storage)

    with pytest.raises(ConnectRefusedError, match="not a restic repository"):
        _replace(workspace, restic, storage, DestinationCopy((pictures,)))
    with pytest.raises(ConnectRefusedError, match="separate from the source"):
        _replace(workspace, restic, cloud / "inside", DestinationCopy((cloud,)))

    assert _state(workspace, storage) == before
    assert restic.operations == []


def test_backups_off_or_already_set_up_are_refused(
    workspace: Workspace, restic: InMemoryRestic, storage: Path, tmp_path: Path
) -> None:
    with pytest.raises(BackupOffError):
        _replace(workspace, restic, storage)
    _saved(workspace, tmp_path / "old")
    with pytest.raises(BackupsSetUpError, match="already set up"):
        _set_up(workspace, restic, storage)

    assert not storage.exists()


def test_a_stale_revision_is_refused_before_restic_runs(
    workspace: Workspace, restic: InMemoryRestic, storage: Path
) -> None:
    """The save is the last step, so it is checked first: a copy that may
    take many minutes is never spent on a stale page."""
    _saved(workspace, storage)
    old = read_settings(workspace).revision
    with workspace.settings_file().open("a", encoding="utf-8") as settings:
        settings.write("  interval_hours: 6\n")
    before = _state(workspace, storage)

    with pytest.raises(SettingsRevisionConflictError):
        _replace(workspace, restic, storage, expected_revision=old)

    assert restic.operations == []
    assert _state(workspace, storage) == before


def test_an_invalid_block_is_refused_by_field_before_restic_runs(
    workspace: Workspace, restic: InMemoryRestic, storage: Path
) -> None:
    with pytest.raises(InvalidSettingsEditError) as invalid:
        _set_up(workspace, restic, storage, interval_hours=5)

    assert "backup.interval_hours" in invalid.value.field_errors
    assert restic.operations == []
    assert not workspace.settings_file().exists()
    assert not (workspace.root / layout.ENV_FILE).exists()


@pytest.mark.parametrize(
    ("source", "answer", "refusal", "words"),
    [
        ("new", None, PasswordTooShortError, "Enter a password"),
        ("new", "short", PasswordTooShortError, "12 characters"),
        ("copy", None, ConnectPasswordError, "Enter the password"),
    ],
)
def test_a_missing_or_short_password_is_refused_before_anything_is_written(
    *,
    workspace: Workspace,
    restic: InMemoryRestic,
    storage: Path,
    tmp_path: Path,
    source: str,
    answer: str | None,
    refusal: type[Exception],
    words: str,
) -> None:
    chosen = NewRepository() if source == "new" else DestinationCopy((_copy(tmp_path / "c"),))
    _saved(workspace, storage)
    before = _state(workspace, storage)

    with pytest.raises(refusal, match=words):
        _replace(workspace, restic, storage, chosen, ask=_Asked(answer))

    assert _state(workspace, storage) == before


def test_a_password_the_environment_overrides_is_refused_for_set_up(
    workspace: Workspace, restic: InMemoryRestic, storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(BACKUP_PASSWORD_VAR, "another password entirely")

    with pytest.raises(RefusedError, match="overrides the saved password"):
        _set_up(workspace, restic, storage)

    assert not workspace.settings_file().exists()


def test_a_stored_password_is_used_without_asking_or_storing_it_again(
    workspace: Workspace, restic: InMemoryRestic, storage: Path
) -> None:
    configure_backups(workspace.root, storage)
    env = (workspace.root / layout.ENV_FILE).read_bytes()
    asked = _Asked()

    done = _replace(workspace, restic, storage, ask=asked)

    assert asked.sources == []
    assert done.stored_password is False
    assert (workspace.root / layout.ENV_FILE).read_bytes() == env


# ------------------------------------------------------------------ the order


def test_the_password_is_stored_first_the_repository_built_beside_and_the_block_saved_last(
    workspace: Workspace, restic: InMemoryRestic, storage: Path
) -> None:
    seen: list[tuple[str, bool, bool, list[str]]] = []

    def started(operation: str) -> None:
        if operation == "init":
            staged = [p.name for p in storage.parent.iterdir() if STAGING_MARK in p.name]
            env = (workspace.root / layout.ENV_FILE).read_text(encoding="utf-8")
            seen.append((env, workspace.settings_file().exists(), storage.exists(), staged))

    restic.on_start = started

    done = _set_up(workspace, restic, storage)

    ((env, settings_saved, storage_named, staged),) = seen
    assert PASSWORD in env
    assert not settings_saved, "the block is saved only once the repository is there"
    assert not storage_named, "the repository takes the folder's name whole"
    assert len(staged) == 1
    assert (storage / "config").is_file()
    assert not any(STAGING_MARK in p.name for p in storage.parent.iterdir())
    assert backup_settings(workspace).repository == storage
    assert (done.connected, done.repository_id, done.stored_password) == (None, "f00d", True)


def test_trying_is_told_before_each_copy_or_before_a_new_repository(
    workspace: Workspace, restic: InMemoryRestic, storage: Path, tmp_path: Path
) -> None:
    told: list[Path | None] = []
    _saved(workspace, storage)
    cloud = _copy(tmp_path / "cloud", "first")
    asked = Provisioning(storage, DestinationCopy((cloud,)), PasswordSource.stored_or(_Asked()))

    _run(workspace, restic, asked, trying=told.append)

    assert told == [cloud]


# --------------------------------------------- failure leaves nothing behind


@pytest.mark.parametrize("existed", [False, True])
@pytest.mark.parametrize("entry", ["set-up", "missing"])
def test_a_failed_init_leaves_the_workspace_as_it_was(
    *,
    workspace: Workspace,
    restic: InMemoryRestic,
    storage: Path,
    tmp_path: Path,
    entry: str,
    existed: bool,
) -> None:
    if entry == "missing":
        _saved(workspace, tmp_path / "old")
    if existed:
        storage.mkdir()
    before = _state(workspace, storage)
    restic.fail("init", ResticError("restic: Fatal: disk full", exit_code=1))
    attempt = _set_up if entry == "set-up" else _replace

    with pytest.raises(ResticError, match="disk full"):
        attempt(workspace, restic, storage)

    assert _state(workspace, storage) == before


@pytest.mark.parametrize("password", ["asked", "from .env"])
def test_a_wrong_password_leaves_nothing_and_says_where_it_came_from(
    workspace: Workspace, restic: InMemoryRestic, storage: Path, tmp_path: Path, password: str
) -> None:
    stored = password == "from .env"
    configure_backups(workspace.root, storage, password=PASSWORD if stored else None)
    cloud = _copy(tmp_path / "cloud", "first")
    restic.password = "the old machine's password"
    before = _state(workspace, storage) | {"cloud": files(cloud)}

    with pytest.raises(ConnectPasswordError) as refused:
        _replace(workspace, restic, storage, DestinationCopy((cloud,)))

    assert refused.value.source == cloud
    assert (f"Set {BACKUP_PASSWORD_VAR} there" in str(refused.value)) is stored
    assert _state(workspace, storage) | {"cloud": files(cloud)} == before


def test_a_copy_that_fails_its_check_leaves_nothing_behind(
    workspace: Workspace, restic: InMemoryRestic, storage: Path, tmp_path: Path
) -> None:
    _saved(workspace, storage)
    cloud = _copy(tmp_path / "cloud", "first")
    before = _state(workspace, storage) | {"cloud": files(cloud)}
    restic.fail("check", ResticError("restic: pack is missing", exit_code=1))

    with pytest.raises(ConnectRefusedError, match="pack is missing"):
        _replace(workspace, restic, storage, DestinationCopy((cloud,)))

    assert _state(workspace, storage) | {"cloud": files(cloud)} == before


@pytest.mark.parametrize("existed", [False, True])
def test_a_save_refused_after_the_copy_takes_the_copy_and_the_password_back(
    *, workspace: Workspace, restic: InMemoryRestic, storage: Path, tmp_path: Path, existed: bool
) -> None:
    """Another edit lands while the copy runs: the save refuses it as stale,
    and the folder the seller named is left as it was, empty or absent."""
    _saved(workspace, tmp_path / "old")
    if existed:
        storage.mkdir()
    cloud = _copy(tmp_path / "cloud", "first")
    before = _state(workspace, storage)

    def edited_meanwhile(operation: str) -> None:
        if operation == "check":
            with workspace.settings_file().open("a", encoding="utf-8") as settings:
                settings.write("  interval_hours: 6\n")

    restic.on_start = edited_meanwhile

    with pytest.raises(SettingsRevisionConflictError):
        _replace(workspace, restic, storage, DestinationCopy((cloud,)))

    after = _state(workspace, storage)
    assert {key: after[key] for key in ("env", "beside", "storage")} == {
        key: before[key] for key in ("env", "beside", "storage")
    }


def test_a_password_set_up_replaces_is_put_back_byte_for_byte(
    workspace: Workspace, restic: InMemoryRestic, storage: Path
) -> None:
    env = workspace.root / layout.ENV_FILE
    env.write_bytes(f"# mine\n{BACKUP_PASSWORD_VAR}=an older password\n".encode())
    before = env.read_bytes()
    restic.fail("init", ResticError("restic: Fatal: disk full", exit_code=1))

    with pytest.raises(ResticError):
        _set_up(workspace, restic, storage)

    assert env.read_bytes() == before


# -------------------------------------------------------------------- copies


def test_the_copy_is_one_way_and_the_storage_folder_gets_its_files(
    workspace: Workspace, restic: InMemoryRestic, storage: Path, tmp_path: Path
) -> None:
    _saved(workspace, tmp_path / "old")
    cloud = _copy(tmp_path / "cloud" / "backups", "first")
    destination_before = files(cloud)

    done = _replace(workspace, restic, storage, DestinationCopy((cloud,)))

    assert files(cloud) == destination_before
    assert files(storage) == {
        n: b for n, b in destination_before.items() if not n.startswith("locks")
    }
    assert backup_settings(workspace).repository == storage
    assert not any(STAGING_MARK in path.name for path in storage.parent.iterdir())
    assert done.stored_password is True
    assert PASSWORD in (workspace.root / layout.ENV_FILE).read_text(encoding="utf-8")


def test_of_several_copies_it_connects_the_complete_one_that_passes_a_check(
    workspace: Workspace, restic: InMemoryRestic, storage: Path, tmp_path: Path
) -> None:
    """One copy still syncing (every file it has, the others have too) is
    never the source; of the complete ones, one failing a check is passed
    over."""
    syncing = _copy(tmp_path / "icloud", "first")
    failing = _copy(tmp_path / "nas", "first", "second")
    passing = _copy(tmp_path / "usb", "first", "second")
    checks: list[str] = []

    def started(operation: str) -> None:
        if operation == "check":
            checks.append(operation)
            if len(checks) == 1:
                raise ResticError("restic: pack is missing", exit_code=1)

    restic.on_start = started
    source = source_for((syncing, failing, passing))

    done = _set_up(workspace, restic, storage, source, destinations=(syncing, failing, passing))

    assert source == DestinationCopy((failing, passing))
    assert done.connected is not None
    assert done.connected.source == passing
    assert len(checks) == 2


def test_a_wrong_password_stops_at_the_first_copy(
    workspace: Workspace, restic: InMemoryRestic, storage: Path, tmp_path: Path
) -> None:
    """Every copy of one repository has the same keys."""
    first = _copy(tmp_path / "icloud", "first")
    second = _copy(tmp_path / "nas", "first")
    _saved(workspace, storage)
    restic.password = "the old machine's password"

    with pytest.raises(ConnectPasswordError):
        _replace(workspace, restic, storage, DestinationCopy((first, second)))

    assert restic.ran("verify_password") == 1


def test_with_no_copy_in_the_destinations_the_source_is_a_new_repository(
    tmp_path: Path,
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()

    assert source_for((tmp_path / "new", empty)) == NewRepository()


def test_destinations_set_up_must_not_choose_between_are_refused(tmp_path: Path) -> None:
    partial = FakeRepository(tmp_path / "partial")
    partial.remove("config")
    icloud = _copy(tmp_path / "icloud", "first")
    nas = _copy(tmp_path / "nas", "other", repository_id="another")
    lacking = (_copy(tmp_path / "a", "first"), _copy(tmp_path / "b", "first"))
    FakeRepository.backup(_as_fake(lacking[0]), "only in a")
    FakeRepository.backup(_as_fake(lacking[1]), "only in b")

    with pytest.raises(ExistingCopiesError, match="no config file"):
        source_for((partial.root,))
    with pytest.raises(ExistingCopiesError, match="two different backup repositories"):
        source_for((icloud, nas))
    with pytest.raises(ExistingCopiesError, match="each has files the other lacks"):
        source_for(lacking)


def _as_fake(root: Path) -> FakeRepository:
    """A handle on a repository folder :func:`_copy` already made."""
    fake = FakeRepository.__new__(FakeRepository)
    fake.root = root
    return fake


# --------------------------------------------------------------- workspace ID


def test_a_new_repository_gets_a_new_workspace_id(
    workspace: Workspace, restic: InMemoryRestic, storage: Path
) -> None:
    done = _set_up(workspace, restic, storage)

    assert done.workspace_id.notice is None
    assert backup_settings(workspace).workspace_id == done.workspace_id.value


@pytest.mark.parametrize(
    ("tags", "adopted"),
    [((None, OURS), True), ((OURS, THEIRS), False)],
)
def test_set_up_adopts_the_one_workspace_id_a_copy_carries(
    *,
    workspace: Workspace,
    restic: InMemoryRestic,
    storage: Path,
    tmp_path: Path,
    tags: tuple[str | None, str],
    adopted: bool,
) -> None:
    """ADR-0061: untagged snapshots are not counted, and several IDs are not
    guessed between."""
    cloud = _copy(tmp_path / "cloud", "first")
    restic.snapshots[:] = [
        MemorySnapshot(NOW - timedelta(days=2), tags[0]),
        MemorySnapshot(NOW - timedelta(days=1), tags[1]),
    ]

    done = _set_up(workspace, restic, storage, DestinationCopy((cloud,)), destinations=(cloud,))

    chosen = backup_settings(workspace).workspace_id
    assert done.connected is not None
    if adopted:
        assert (chosen, done.connected.notice) == (OURS, None)
    else:
        assert chosen not in (None, OURS, THEIRS)
        assert done.connected.notice == SEVERAL_WORKSPACES


@pytest.mark.parametrize("saved_id", [WORKSPACE_ID, None])
def test_a_saved_block_keeps_its_workspace_id_or_adopts_the_copy_s(
    workspace: Workspace, restic: InMemoryRestic, storage: Path, tmp_path: Path, saved_id: str
) -> None:
    configure_backups(workspace.root, storage, password=None, workspace_id=saved_id)
    cloud = _copy(tmp_path / "cloud", "first")
    restic.snapshots[:] = [MemorySnapshot(NOW - timedelta(days=1), OURS)]

    _replace(workspace, restic, storage, DestinationCopy((cloud,)))

    assert backup_settings(workspace).workspace_id == (saved_id or OURS)


def test_a_saved_block_takes_the_folder_the_seller_confirmed(
    workspace: Workspace, restic: InMemoryRestic, tmp_path: Path
) -> None:
    _saved(workspace, tmp_path / "old")
    chosen = tmp_path / "new-backups"

    _replace(workspace, restic, chosen)

    assert backup_settings(workspace).repository == chosen
    assert (chosen / "config").is_file()

from __future__ import annotations

import hashlib
import itertools
import math
import os
import random
import re
import secrets
import stat
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import BinaryIO, Literal

from etsy_listings.core.errors import ConflictError, UserFacingError

READ_ORDER = ("snapshots", "index", "data", "keys", "config")
"""restic reads snapshots, then indexes, then packs, the reverse of how it
writes them (restic's design document, *Read and Write Ordering*). Listed in
this order, every pack a listed index names was already on disk when
``data/`` was listed, even while another restic process writes."""
WRITE_ORDER = ("config", "keys", "data", "index", "snapshots")
DELETE_ORDER = tuple(reversed(WRITE_ORDER))
"""A pack leaves the index that names it before the pack itself goes."""
CONFIG = "config"
CHUNK = 1024 * 1024
TEMP_MARK = ".copying-"
"""The copy's own temporary names: ``<final name>.copying-<8 hex>``."""
_HASH = re.compile(r"[0-9a-f]{64}")
_TEMP = re.compile(r"(.+)\.copying-[0-9a-f]{8}")
_RESTIC_TEMP = "-tmp-"
"""restic's local backend writes ``<name>-tmp-<random>`` before renaming."""

CopyOutcome = Literal["copied", "unreachable", "changed", "damaged", "failed", "stopped"]
"""``damaged``: a local file no longer matches its name, the fault a failed
``restic check`` reports."""


@dataclass(frozen=True)
class CopyStep:
    action: Literal["copied", "deleted", "set_aside"]
    name: str


@dataclass(frozen=True)
class CopyHooks:
    """Observation points, for progress and for tests: ``after_listing``
    runs once both folders are listed, before anything is written;
    ``planned`` then hears how many files the destination lacks;
    ``observe`` hears each operation as it completes."""

    after_listing: Callable[[], None] = lambda: None
    planned: Callable[[int], None] = lambda _: None
    observe: Callable[[CopyStep], None] = lambda _: None


@dataclass(frozen=True)
class ChangedFile:
    """A destination file that differs from the local one of its name. For
    ``config``, or a change the sample check found, the sizes can match."""

    name: str
    expected_size: int
    actual_size: int


@dataclass(frozen=True)
class CopyResult:
    destination: Path
    outcome: CopyOutcome
    message: str | None = None
    copied: tuple[str, ...] = ()
    deleted: tuple[str, ...] = ()
    changed: tuple[ChangedFile, ...] = ()
    unexpected: tuple[str, ...] = ()
    """Names restic would never write, such as an iCloud conflict copy."""


def restic_name(name: str) -> bool:
    match name.split("/"):
        case [top] if top == CONFIG:
            return True
        case [top, file] if top in ("keys", "index", "snapshots"):
            return bool(_HASH.fullmatch(file))
        case ["data", fan, file]:
            return bool(_HASH.fullmatch(file)) and fan == file[:2]
    return False


def _walk(path: Path) -> Iterator[tuple[Path, os.stat_result]]:
    try:
        info = path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISDIR(info.st_mode) and not path.is_junction():
        for child in sorted(path.iterdir()):
            yield from _walk(child)
    else:
        yield path, info


def list_repository(root: Path) -> dict[str, int]:
    """``/`` path to size, in restic's read order, without ``locks/`` and
    restic's temporary names."""
    before = _reference_directories(root)
    listing: dict[str, int] = {}
    for top in READ_ORDER:
        for path, info in _walk(root / top):
            name = path.relative_to(root).as_posix()
            if stat.S_ISREG(info.st_mode) and restic_name(name):
                listing[name] = info.st_size
    if _reference_directories(root) != before:
        # Forget or prune may remove snapshots or indexes before deleting packs.
        raise OSError(f"{root} changed while it was being listed. Try the copy again.")
    return listing


def _reference_directories(root: Path) -> list[tuple[int, int, int, int, int] | None]:
    references: list[tuple[int, int, int, int, int] | None] = []
    for top in ("snapshots", "index"):
        try:
            references.append(_identity((root / top).lstat()))
        except FileNotFoundError:
            references.append(None)
    return references


def list_destination(root: Path) -> dict[str, os.stat_result]:
    others = sorted(path.name for path in root.iterdir() if path.name not in READ_ORDER)
    found: dict[str, os.stat_result] = {}
    for top in (*READ_ORDER, *others):
        if top == "locks":
            continue
        for path, info in _walk(root / top):
            name = path.relative_to(root).as_posix()
            if _RESTIC_TEMP not in path.name:
                found[name] = info
    return found


def _in_order(names: list[str], order: tuple[str, ...]) -> list[str]:
    return sorted(names, key=lambda name: order.index(name.split("/")[0]))


@dataclass
class Sorted:
    """A destination's files against the local listing (spec step 2)."""

    missing: list[str] = field(default_factory=list)
    expired: dict[str, os.stat_result] = field(default_factory=dict)
    changed: list[ChangedFile] = field(default_factory=list)
    unexpected: list[str] = field(default_factory=list)
    temporaries: dict[str, os.stat_result] = field(default_factory=dict)
    config: os.stat_result | None = None


def sort_destination(
    repository: Path, destination: Path, local: dict[str, int], suspect: frozenset[str]
) -> Sorted:
    """Sort ``destination``'s files. ``suspect`` names present files known
    to be changed although their size matches."""
    found = list_destination(destination)
    result = Sorted(
        missing=_in_order([name for name in local if name not in found], WRITE_ORDER),
        config=found.get(CONFIG),
    )
    if result.config is None and any(restic_name(name) for name in found):
        # A sync client can remove config before the rest of the old copy.
        result.changed.append(ChangedFile(CONFIG, local[CONFIG], 0))
    for name, info in found.items():
        if name not in local:
            _classify_other(result, name, info)
        elif (
            not stat.S_ISREG(info.st_mode)
            or (name != CONFIG and name in suspect)
            or _differs(repository, destination, name, local[name], info.st_size)
        ):
            result.changed.append(ChangedFile(name, local[name], info.st_size))
    return result


def _classify_other(result: Sorted, name: str, info: os.stat_result) -> None:
    regular = stat.S_ISREG(info.st_mode)
    temporary = _TEMP.fullmatch(name)
    if regular and restic_name(name):
        result.expired[name] = info
    elif regular and temporary and restic_name(temporary[1]):
        result.temporaries[name] = info
    else:
        result.unexpected.append(name)


def _differs(repository: Path, destination: Path, name: str, expected: int, actual: int) -> bool:
    if name == CONFIG:
        return (repository / name).read_bytes() != (destination / name).read_bytes()
    return expected != actual


def _changed_message(changed: list[ChangedFile]) -> str:
    listed = "; ".join(
        f"{file.name} ({file.expected_size:,} bytes expected, {file.actual_size:,} found)"
        for file in changed
    )
    return f"Something else changed files in this copy, so nothing more is copied there: {listed}."


class DestinationNotFoundError(UserFacingError):
    pass


def create_destination(destination: Path) -> None:
    """Set-up's one way to make a destination folder: inside a folder that
    exists, and never over one that is already there."""
    if destination.is_dir():
        return
    if not destination.parent.is_dir():
        raise DestinationNotFoundError(
            f"{destination.parent} was not found, so {destination.name} cannot be "
            "created there. Connect the drive, share or sync folder first."
        )
    destination.mkdir()


def _unreachable(destination: Path) -> CopyResult:
    """A copy never creates its destination: a missing folder can mean a
    sync client signed out with its folder left behind, where a new folder
    would fill up and never sync."""
    return CopyResult(
        destination,
        "unreachable",
        f"Folder not found: {destination}. It is caught up once it is back.",
    )


def copy_repository(
    repository: Path,
    destination: Path,
    *,
    suspect: frozenset[str] = frozenset(),
    hooks: CopyHooks | None = None,
    cancel: threading.Event | None = None,
) -> CopyResult:
    """Bring ``destination`` up to ``repository`` (spec steps 1 to 6).
    ``suspect`` names files the sample check found changed."""
    hooks = hooks or CopyHooks()
    try:
        local = list_repository(repository)
    except OSError as exc:
        return CopyResult(
            destination, "failed", f"The backup storage folder could not be listed: {exc}"
        )
    if CONFIG not in local:
        # Never mirror an empty listing: that would delete the whole copy.
        return CopyResult(destination, "failed", f"{repository} is not a restic repository.")
    if not destination.is_absolute() or not destination.is_dir():
        return _unreachable(destination)
    try:
        plan = sort_destination(repository, destination, local, suspect)
    except OSError:
        return _unreachable(destination)
    hooks.after_listing()
    hooks.planned(len(plan.missing))
    copy = _Copy(repository, destination, plan, hooks.observe, cancel or threading.Event())
    return copy.start()


@dataclass
class _Copy:
    repository: Path
    destination: Path
    plan: Sorted
    observe: Callable[[CopyStep], None]
    cancel: threading.Event
    steps: list[CopyStep] = field(default_factory=list)

    def start(self) -> CopyResult:
        if not self.destination.is_dir():
            return _unreachable(self.destination)
        if self.plan.changed:
            return self.result("changed", _changed_message(self.plan.changed))
        return self.apply()

    def apply(self) -> CopyResult:
        """Copy in write order, delete in reverse, then drop leftovers."""
        try:
            for name in self.plan.missing:
                self._continue()
                _copy_file(self.repository, self.destination, name)
                self._done("copied", name)
            for name in _in_order(list(self.plan.expired), DELETE_ORDER):
                self._continue()
                self._expire(name)
            for name, expected in self.plan.temporaries.items():
                self._continue()
                self._remove_temporary(name, expected)
        except _StoppedError:
            return self.result("stopped", "The copy was stopped; the next run finishes it.")
        except _DestinationChangedError as exc:
            self.plan.changed.append(exc.file)
            return self.result("changed", _changed_message(self.plan.changed))
        except DamagedError as exc:
            return self.result("damaged", str(exc))
        except OSError as exc:
            return self.result("failed", _failure(exc, self.repository, self.destination))
        return self.result("copied")

    def _expire(self, name: str) -> None:
        config = self.plan.config
        assert config is not None  # Expiry requires a matching config when we list the copy.
        if not _unchanged(self.destination / CONFIG, config, CONFIG):
            raise _DestinationChangedError(ChangedFile(CONFIG, config.st_size, 0))
        path = _destination_path(self.destination, name)
        expected = self.plan.expired[name]
        if not _unchanged(path, expected, name):
            return
        if _sha256(path) != path.name:
            self.plan.unexpected.append(name)
            return
        if _unchanged(path, expected, name):
            path.unlink(missing_ok=True)
            self._done("deleted", name)

    def _remove_temporary(self, name: str, expected: os.stat_result) -> None:
        path = _destination_path(self.destination, name)
        if _unchanged(path, expected, name):
            path.unlink(missing_ok=True)

    def _continue(self) -> None:
        if self.cancel.is_set():
            raise _StoppedError

    def _done(self, action: Literal["copied", "deleted"], name: str) -> None:
        step = CopyStep(action, name)
        self.steps.append(step)
        self.observe(step)

    def result(self, outcome: CopyOutcome, message: str | None = None) -> CopyResult:
        return CopyResult(
            self.destination,
            outcome,
            message,
            copied=tuple(step.name for step in self.steps if step.action == "copied"),
            deleted=tuple(step.name for step in self.steps if step.action == "deleted"),
            changed=tuple(self.plan.changed),
            unexpected=tuple(self.plan.unexpected),
        )


def _failure(exc: OSError, repository: Path, destination: Path) -> str:
    # A rename's error names the target second.
    path = Path(exc.filename2 or exc.filename or "")
    if isinstance(exc, FileNotFoundError) and path.is_relative_to(repository):
        return (
            f"{path.relative_to(repository).as_posix()} left the backup storage folder "
            "while it was being copied, as a prune does; the next run catches the copy up."
        )
    if isinstance(exc, FileExistsError) and path.is_relative_to(destination):
        return (
            f"{path.relative_to(destination).as_posix()} appeared in the copy while copying "
            "and was left as it is; the next run looks at it again."
        )
    return f"The copy stopped: {exc}"


class _StoppedError(Exception):
    pass


class _DestinationChangedError(Exception):
    def __init__(self, file: ChangedFile) -> None:
        self.file = file


def _unchanged(path: Path, expected: os.stat_result, name: str) -> bool:
    try:
        current = path.lstat()
    except FileNotFoundError:
        return False
    if _identity(current) != _identity(expected):
        raise _DestinationChangedError(ChangedFile(name, expected.st_size, current.st_size))
    return True


def _identity(info: os.stat_result) -> tuple[int, int, int, int, int]:
    return info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns


def _destination_path(root: Path, name: str) -> Path:
    path = root / name
    if not root.is_dir():
        raise FileNotFoundError(f"Destination folder disappeared: {root}")
    for parent in path.parents:
        if parent == root:
            break
        if parent.is_symlink() or parent.is_junction():
            raise OSError(f"Refusing to write through a linked directory: {parent}")
    return path


class DamagedError(Exception):
    """A local repository file whose contents no longer match its name."""


def _copy_file(repository: Path, destination: Path, name: str) -> None:
    target = _destination_path(destination, name)
    folder = destination
    for part in Path(name).parts[:-1]:
        folder /= part
        folder.mkdir(exist_ok=True)
    with _temporary(target) as (temp, writer):
        digest = _stream(repository / name, writer)
        writer.close()
        if name != CONFIG and digest != target.name:
            # Every name but config is the SHA-256 of the contents.
            raise DamagedError(
                f"{name} in the backup storage folder is damaged: its contents "
                "no longer match its name."
            )
        _publish(temp, target)


@contextmanager
def _temporary(target: Path) -> Iterator[tuple[Path, BinaryIO]]:
    """A new temporary name beside ``target``, removed unless renamed."""
    temp = target.with_name(f"{target.name}{TEMP_MARK}{secrets.token_hex(4)}")
    writer = temp.open("xb")
    try:
        yield temp, writer
    finally:
        writer.close()
        temp.unlink(missing_ok=True)


def _stream(source: Path, writer: BinaryIO) -> str:
    digest = hashlib.sha256()
    with source.open("rb") as reader:
        while chunk := reader.read(CHUNK):
            digest.update(chunk)
            writer.write(chunk)
        writer.flush()
        os.fsync(writer.fileno())
    return digest.hexdigest()


def _publish(temp: Path, target: Path) -> None:
    """Give ``temp`` the name ``target`` only while nothing has it. Windows'
    rename refuses an existing name; elsewhere rename would replace it, so
    a hard link takes the name instead (``_temporary`` drops ``temp``)."""
    if os.name == "nt":
        temp.rename(target)
    else:
        os.link(temp, target)


SAMPLE_FRACTION = 0.05
"""The monthly check reads 5% of a destination's files (spec, *Checking a
destination*)."""
CheckOutcome = Literal["ok", "changed", "unreachable"]


@dataclass(frozen=True)
class DestinationCheck:
    destination: Path
    outcome: CheckOutcome
    checked: tuple[str, ...] = ()
    changed: tuple[ChangedFile, ...] = ()
    message: str | None = None


def check_destination(
    repository: Path,
    destination: Path,
    *,
    fraction: float = SAMPLE_FRACTION,
    rng: random.Random | None = None,
) -> DestinationCheck:
    """Hash a random sample of ``destination``'s files against their names
    and compare ``config`` with the local one. Reads only: no lock, no
    password, no restic."""
    try:
        return _sample_destination(repository, destination, fraction, rng)
    except OSError as exc:
        return DestinationCheck(
            destination, "unreachable", message=f"{destination} could not be checked: {exc}."
        )


def _sample_destination(
    repository: Path, destination: Path, fraction: float, rng: random.Random | None
) -> DestinationCheck:
    local = list_repository(repository)
    if CONFIG not in local:
        raise FileNotFoundError(f"{repository} has no config")
    shared = [
        name
        for name, info in list_destination(destination).items()
        if name in local and name != CONFIG and stat.S_ISREG(info.st_mode)
    ]
    count = min(len(shared), math.ceil(len(shared) * fraction))
    sample = sorted((rng or random.SystemRandom()).sample(shared, count))
    changed = [
        ChangedFile(name, local[name], (destination / name).stat().st_size)
        for name in sample
        if _sha256(destination / name) != name.rsplit("/", 1)[-1]
    ]
    config = destination / CONFIG
    if config.read_bytes() != (repository / CONFIG).read_bytes():
        changed.insert(0, ChangedFile(CONFIG, local[CONFIG], config.stat().st_size))
    if not changed:
        return DestinationCheck(destination, "ok", tuple(sample))
    listed = ", ".join(file.name for file in changed)
    message = f"Files in this copy no longer match the backup storage folder: {listed}."
    return DestinationCheck(destination, "changed", tuple(sample), tuple(changed), message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as reader:
        while chunk := reader.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


class ForeignCopyError(ConflictError):
    def __init__(self, destination: Path) -> None:
        super().__init__(
            f"config in {destination} is missing or differs from the backup storage "
            "folder's config: the copy may "
            "belong to another repository, such as one from before Create a new "
            "repository, or its config may be damaged. Repair would set config aside, "
            "and the next copy would then delete every other file there as expired, so "
            "nothing was moved. To keep those backups, use Connect an existing repository "
            "with that folder; otherwise move it somewhere else and create an empty "
            "folder in its place, or change the destination in Setup."
        )


def holds_repository(folder: Path) -> bool:
    return any((folder / name).exists() for name in READ_ORDER)


@dataclass(frozen=True)
class RepairResult:
    set_aside: Path | None
    """``<destination>-set-aside-<date>``; None when nothing was moved."""
    moved: tuple[str, ...]
    copy: CopyResult


def repair_destination(
    repository: Path,
    destination: Path,
    *,
    today: date,
    suspect: frozenset[str] = frozenset(),
) -> RepairResult:
    """Move changed and unexpected files to a new sibling folder, deleting
    nothing, then copy again (spec, *Changed and unexpected files*)."""
    local = list_repository(repository)
    if CONFIG not in local or not destination.is_absolute() or not destination.is_dir():
        return RepairResult(None, (), copy_repository(repository, destination))
    plan = sort_destination(repository, destination, local, suspect)
    if any(file.name == CONFIG for file in plan.changed):
        # Telling another repository's config from a damaged one needs the
        # password, so either way nothing moves (plan, PR 8).
        raise ForeignCopyError(destination)
    moving = [file.name for file in plan.changed] + plan.unexpected
    moving.extend(
        name
        for name in plan.expired
        if _sha256(_destination_path(destination, name)) != Path(name).name
    )
    if not moving:
        return RepairResult(None, (), copy_repository(repository, destination))
    aside = _new_sibling(destination, today)
    for name in moving:
        target = aside / name
        target.parent.mkdir(parents=True, exist_ok=True)
        # A new folder, so the rename can replace nothing.
        _destination_path(destination, name).rename(target)
    return RepairResult(aside, tuple(moving), copy_repository(repository, destination))


def planned_set_aside(destination: Path, today: date) -> Path:
    """The folder a repair today would set files aside in: the first of
    ``<destination>-set-aside-<date>``, ``-2``, ``-3``... not taken yet.
    Reads only; :func:`repair_destination` creates it."""
    return next(path for path in _set_aside_names(destination, today) if not path.exists())


def _set_aside_names(destination: Path, today: date) -> Iterator[Path]:
    base = f"{destination.name}-set-aside-{today.isoformat()}"
    yield destination.with_name(base)
    for attempt in itertools.count(2):
        yield destination.with_name(f"{base}-{attempt}")


def _new_sibling(destination: Path, today: date) -> Path:
    """The first free set-aside name, created empty; a race that takes it
    first moves on to the next."""
    names = _set_aside_names(destination, today)
    while True:
        candidate = next(names)
        try:
            candidate.mkdir()
        except FileExistsError:
            continue
        return candidate

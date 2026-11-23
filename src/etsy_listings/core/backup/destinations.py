"""Copy the backup storage folder one way to a destination folder
(workspace-backup spec, *Copy to destinations*).

Plain file operations with no restic, so any folder works, a NAS share
included. The copy only adds files under names the destination lacks and
deletes names the local repository no longer has. It never overwrites a file
and never deletes one it does not recognise.
"""

from __future__ import annotations

import errno
import hashlib
import math
import os
import random
import re
import secrets
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Literal

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
_TEMP = re.compile(r".+\.copying-[0-9a-f]{8}")
_RESTIC_TEMP = "-tmp-"
"""restic's local backend writes ``<name>-tmp-<random>`` before renaming."""

CopyOutcome = Literal["copied", "unreachable", "changed", "damaged", "failed", "stopped"]
"""``damaged``: a local file no longer matches its name, the fault a failed
``restic check`` reports."""


@dataclass(frozen=True)
class CopyStep:
    """One file operation, reported once it is done."""

    action: Literal["copied", "deleted", "set_aside"]
    name: str


@dataclass(frozen=True)
class CopyHooks:
    """Observation points, for progress and for tests: ``after_listing``
    runs once both folders are listed, before anything is written;
    ``observe`` hears each operation as it completes."""

    after_listing: Callable[[], None] = lambda: None
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
    """Whether restic writes a file by this ``/`` path."""
    match name.split("/"):
        case [top] if top == CONFIG:
            return True
        case [top, file] if top in ("keys", "index", "snapshots"):
            return bool(_HASH.fullmatch(file))
        case ["data", fan, file]:
            return bool(_HASH.fullmatch(file)) and file.startswith(fan)
    return False


def _walk(folder: Path) -> Iterator[Path]:
    if folder.is_file():
        yield folder
    elif folder.is_dir():
        yield from sorted(path for path in folder.rglob("*") if path.is_file())


def list_repository(root: Path) -> dict[str, int]:
    """``/`` path to size, in restic's read order, without ``locks/`` and
    restic's temporary names."""
    listing: dict[str, int] = {}
    for top in READ_ORDER:
        for path in _walk(root / top):
            if _RESTIC_TEMP not in path.name:
                listing[path.relative_to(root).as_posix()] = path.stat().st_size
    return listing


def list_destination(root: Path) -> dict[str, int]:
    """Every file, without ``locks/`` and restic's temporary names: restic
    writes those itself when it opens a destination, say to restore."""
    return {
        name: path.stat().st_size
        for path in _walk(root)
        if not (name := path.relative_to(root).as_posix()).startswith("locks/")
        and _RESTIC_TEMP not in path.name
    }


def _in_order(names: list[str], order: tuple[str, ...]) -> list[str]:
    return sorted(names, key=lambda name: order.index(name.split("/")[0]))


@dataclass
class Sorted:
    """A destination's files against the local listing (spec step 2)."""

    missing: list[str] = field(default_factory=list)
    expired: list[str] = field(default_factory=list)
    changed: list[ChangedFile] = field(default_factory=list)
    unexpected: list[str] = field(default_factory=list)
    temporaries: list[str] = field(default_factory=list)


def sort_destination(
    repository: Path, destination: Path, local: dict[str, int], suspect: frozenset[str]
) -> Sorted:
    """Sort ``destination``'s files. ``suspect`` names present files known
    to be changed although their size matches."""
    found = list_destination(destination)
    result = Sorted(missing=_in_order([name for name in local if name not in found], WRITE_ORDER))
    for name, size in found.items():
        if name in local:
            if name in suspect or _differs(repository, destination, name, local[name], size):
                result.changed.append(ChangedFile(name, local[name], size))
        elif restic_name(name):
            result.expired.append(name)
        elif _TEMP.fullmatch(name):
            result.temporaries.append(name)
        else:
            result.unexpected.append(name)
    result.expired = _in_order(result.expired, DELETE_ORDER)
    return result


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


def reachable(destination: Path) -> bool:
    """A destination folder, or a new one whose parent is there. A missing
    parent is a drive, share or sync folder that is offline."""
    return destination.is_dir() or destination.parent.is_dir()


def _unreachable(destination: Path) -> CopyResult:
    return CopyResult(
        destination,
        "unreachable",
        f"{destination} could not be reached; the next run catches it up.",
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
    local = list_repository(repository)
    if CONFIG not in local:
        # Never mirror an empty listing: that would delete the whole copy.
        return CopyResult(destination, "failed", f"{repository} is not a restic repository.")
    if not reachable(destination):
        return _unreachable(destination)
    try:
        destination.mkdir(exist_ok=True)
        plan = sort_destination(repository, destination, local, suspect)
    except OSError:
        return _unreachable(destination)
    hooks.after_listing()
    copy = _Copy(repository, destination, plan, hooks.observe, cancel or threading.Event())
    if plan.changed:
        return copy.result("changed", _changed_message(plan.changed))
    return copy.apply()


@dataclass
class _Copy:
    repository: Path
    destination: Path
    plan: Sorted
    observe: Callable[[CopyStep], None]
    cancel: threading.Event
    steps: list[CopyStep] = field(default_factory=list)

    def apply(self) -> CopyResult:
        """Copy in write order, delete in reverse, then drop leftovers."""
        try:
            for name in self.plan.missing:
                self._continue()
                _copy_file(self.repository / name, self.destination / name, name)
                self._done("copied", name)
            for name in self.plan.expired:
                self._continue()
                (self.destination / name).unlink(missing_ok=True)
                self._done("deleted", name)
            for name in self.plan.temporaries:
                (self.destination / name).unlink(missing_ok=True)
        except _StoppedError:
            return self.result("stopped", "The copy was stopped; the next run finishes it.")
        except DamagedError as exc:
            return self.result("damaged", str(exc))
        except OSError as exc:
            return self.result("failed", _failure(exc, self.repository, self.destination))
        return self.result("copied")

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


class DamagedError(Exception):
    """A local repository file whose contents no longer match its name."""


def _copy_file(source: Path, target: Path, name: str) -> None:
    """Stream ``source`` to a temporary name beside ``target``, hashing it,
    then give it its name."""
    target.parent.mkdir(parents=True, exist_ok=True)
    with _temporary(target) as temp:
        digest = _stream(source, temp)
        if name != CONFIG and digest != target.name:
            # Every name but config is the SHA-256 of the contents.
            raise DamagedError(
                f"{name} in the backup storage folder is damaged: its contents "
                "no longer match its name."
            )
        _publish(temp, target)


@contextmanager
def _temporary(target: Path) -> Iterator[Path]:
    """A new temporary name beside ``target``, removed unless renamed."""
    temp = target.with_name(f"{target.name}{TEMP_MARK}{secrets.token_hex(4)}")
    try:
        yield temp
    finally:
        temp.unlink(missing_ok=True)


def _stream(source: Path, temp: Path) -> str:
    """Copy ``source`` into the new file ``temp``, flushed to disk; the
    SHA-256 of what was written."""
    digest = hashlib.sha256()
    with source.open("rb") as reader, temp.open("xb") as writer:
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
        return
    try:
        os.link(temp, target)
    except FileExistsError:
        raise
    except OSError:
        # A filesystem without hard links: check, then rename.
        if target.exists():
            raise FileExistsError(errno.EEXIST, "File exists", str(target)) from None
        temp.rename(target)


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
    if not destination.is_dir():
        return DestinationCheck(
            destination, "unreachable", message=f"{destination} could not be reached."
        )
    local = list_repository(repository)
    shared = [name for name in list_destination(destination) if name in local and name != CONFIG]
    count = min(len(shared), math.ceil(len(shared) * fraction))
    sample = sorted((rng or random.SystemRandom()).sample(shared, count))
    changed = [
        ChangedFile(name, local[name], (destination / name).stat().st_size)
        for name in sample
        if _sha256(destination / name) != name.rsplit("/", 1)[-1]
    ]
    config = destination / CONFIG
    if config.is_file() and config.read_bytes() != (repository / CONFIG).read_bytes():
        changed.insert(0, ChangedFile(CONFIG, local[CONFIG], config.stat().st_size))
    return DestinationCheck(
        destination, "changed" if changed else "ok", tuple(sample), tuple(changed)
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as reader:
        while chunk := reader.read(CHUNK):
            digest.update(chunk)
    return digest.hexdigest()


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
    if CONFIG not in local or not destination.is_dir():
        return RepairResult(None, (), copy_repository(repository, destination))
    plan = sort_destination(repository, destination, local, suspect)
    moving = [file.name for file in plan.changed] + plan.unexpected
    if not moving:
        return RepairResult(None, (), copy_repository(repository, destination))
    aside = _new_sibling(destination, f"set-aside-{today.isoformat()}")
    for name in moving:
        target = aside / name
        target.parent.mkdir(parents=True, exist_ok=True)
        # A new folder, so the rename can replace nothing.
        (destination / name).rename(target)
    return RepairResult(aside, tuple(moving), copy_repository(repository, destination))


def _new_sibling(destination: Path, suffix: str) -> Path:
    """``<destination>-<suffix>``, then ``-2``, ``-3``..., created empty."""
    base = f"{destination.name}-{suffix}"
    attempt = 1
    while True:
        candidate = destination.with_name(base if attempt == 1 else f"{base}-{attempt}")
        try:
            candidate.mkdir()
        except FileExistsError:
            attempt += 1
        else:
            return candidate

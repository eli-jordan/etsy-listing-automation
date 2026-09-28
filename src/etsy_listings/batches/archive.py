"""Reading design PNGs out of one dropped ZIP (spec *Accepted input*; A45;
batch plan PR 7).

A ZIP is vendor-agnostic: every PNG at any folder depth is a candidate
design, decided by its magic bytes rather than its extension, and every other
file is ignored and named. :func:`receive` streams the ZIP to disk under the
compressed limit; :func:`open_archive` then checks the whole central
directory before the caller stores a byte of any entry, and
:meth:`Archive.read` streams one entry at a time. There is deliberately no
``extractall``: an entry never becomes a path, only the bytes the caller
hashes, so a name is checked for what it says, not trusted to land anywhere.

The size limits are checked against the sizes the central directory
declares, which is enough: `zipfile` reads an entry's compressed bytes up to
its declared ``compress_size``, cuts the output at its declared
``file_size`` and checks the CRC at the end, so a lying header yields fewer
bytes or a refusal, never more.
"""

from __future__ import annotations

import re
import stat
import zipfile
import zlib
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

# A45: safety limits, not settings. Module attributes so a test can lower them.
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_EXPANDED_BYTES = 1024 * 1024 * 1024
MAX_ENTRIES = 2000
MAX_RATIO = 100

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
_CHUNK = 1024 * 1024
_ENCRYPTED = 0x1
_DRIVE = re.compile(r"^[A-Za-z]:")

_REEXPORT = "Export it again, or unzip it and drop the PNGs themselves."
_SPLIT = "Split it into smaller ZIPs, or unzip it and drop the PNGs themselves."
_UNREADABLE = (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError)
"""What `zipfile` raises for an archive it cannot read: a bad header or CRC,
corrupt deflate data, a truncated entry, a compression method it lacks, or a
password it was not given."""


class ArchiveRefused(ValueError):
    """The ZIP cannot be staged. ``message`` is about the archive (*It
    ...*, under a heading naming it); ``remedy`` says what to do instead."""

    def __init__(self, message: str, remedy: str) -> None:
        self.message = message
        self.remedy = remedy
        super().__init__(f"{message} {remedy}")


def receive(chunks: Iterable[bytes], path: Path) -> None:
    """Write the dropped ZIP to ``path`` with a running byte count (A45)."""
    size = 0
    with path.open("wb") as out:
        for chunk in chunks:
            size += len(chunk)
            if size > MAX_ARCHIVE_BYTES:
                raise ArchiveRefused(f"It is larger than {MAX_ARCHIVE_BYTES // 2**20} MiB.", _SPLIT)
            out.write(chunk)


@dataclass(frozen=True)
class Archive:
    """An opened ZIP whose every entry passed A45's checks."""

    _zip: zipfile.ZipFile
    _pngs: dict[str, zipfile.ZipInfo]
    ignored: list[str]
    """Every file that is not a PNG, by its path in the ZIP (UI doc §5)."""

    @property
    def pngs(self) -> list[str]:
        """Every PNG's path in the ZIP, in archive order."""
        return list(self._pngs)

    def read(self, name: str) -> Iterator[bytes]:
        """One PNG's bytes, a chunk at a time."""
        try:
            with self._zip.open(self._pngs[name]) as entry:
                while chunk := entry.read(_CHUNK):
                    yield chunk
        except _UNREADABLE as exc:
            raise ArchiveRefused(f"{name} inside it cannot be read.", _REEXPORT) from exc


def _unsafe_name(name: str) -> str | None:
    """Why ``name`` cannot become a plain uploaded file, if it cannot. A
    backslash is a separator here whatever the platform, since a ZIP made
    on Windows may use one and `zipfile` converts it only on Windows."""
    posix = name.replace("\\", "/")
    if posix.startswith("/") or _DRIVE.match(posix):
        return "is an absolute path"
    if ".." in posix.split("/"):
        return "points outside the ZIP"
    return None


def _normalised(name: str) -> str:
    """The name as the file it would be: separators unified, empty and ``.``
    segments dropped, casefolded as Windows compares it."""
    parts = [part for part in name.replace("\\", "/").split("/") if part not in ("", ".")]
    return "/".join(parts).casefold()


def _unsafe_type(info: zipfile.ZipInfo) -> str | None:
    """A Unix mode in the high bits of ``external_attr`` that is not a plain
    file or directory. Zero -- a ZIP made on Windows -- is a plain file."""
    mode = info.external_attr >> 16
    if stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR):
        return None
    return "is a symbolic link" if stat.S_ISLNK(mode) else "is not a plain file"


def _check(infos: list[zipfile.ZipInfo]) -> None:
    """Every entry, before any is read: A45's per-entry refusals."""
    if len(infos) > MAX_ENTRIES:
        raise ArchiveRefused(
            f"It holds {len(infos)} entries, and a ZIP can hold at most {MAX_ENTRIES}.",
            "Unzip it and drop the PNGs, or split it into smaller ZIPs.",
        )
    seen: set[str] = set()
    for info in infos:
        name = info.filename
        problem = _unsafe_name(name) or _unsafe_type(info)
        if problem:
            raise ArchiveRefused(f"{name} inside it {problem}.", _REEXPORT)
        if info.flag_bits & _ENCRYPTED:
            raise ArchiveRefused(
                f"{name} inside it is encrypted.",
                "Export it again without a password, or unzip it and drop the PNGs themselves.",
            )
        normalised = _normalised(name)
        if normalised in seen:
            raise ArchiveRefused(f"{name} appears in it twice.", _REEXPORT)
        seen.add(normalised)


def _check_sizes(pngs: list[zipfile.ZipInfo]) -> None:
    """The size limits, over the PNGs: the only entries ever expanded. The
    rest are read eight bytes deep to learn they are not PNGs, so an
    ignored file cannot be a bomb and is not refused for compressing well
    (a ``.DS_Store`` of zeros is not an attack)."""
    total = 0
    for info in pngs:
        if info.file_size > MAX_RATIO * max(info.compress_size, 1):
            raise ArchiveRefused(
                f"{info.filename} inside it unpacks to more than {MAX_RATIO} times its "
                "packed size.",
                _REEXPORT,
            )
        total += info.file_size
    if total > MAX_EXPANDED_BYTES:
        raise ArchiveRefused(f"It unpacks to more than {MAX_EXPANDED_BYTES // 2**20} MiB.", _SPLIT)


def _survey(archive: zipfile.ZipFile) -> Archive:
    infos = archive.infolist()
    _check(infos)
    pngs: dict[str, zipfile.ZipInfo] = {}
    ignored: list[str] = []
    for info in infos:
        if info.is_dir():
            continue
        try:
            with archive.open(info) as entry:
                head = entry.read(len(PNG_MAGIC))
        except _UNREADABLE as exc:
            raise ArchiveRefused(f"{info.filename} inside it cannot be read.", _REEXPORT) from exc
        if head == PNG_MAGIC:
            pngs[info.filename] = info
        else:
            ignored.append(info.filename)
    if not pngs:
        raise ArchiveRefused("It holds no PNG files.", "Check it is the export you meant.")
    _check_sizes(list(pngs.values()))
    return Archive(archive, pngs, ignored)


@contextmanager
def open_archive(path: Path) -> Iterator[Archive]:
    """The ZIP at ``path``, checked, or :class:`ArchiveRefused`."""
    try:
        archive = zipfile.ZipFile(path)
    except _UNREADABLE as exc:
        raise ArchiveRefused("It is not a ZIP that can be read.", _REEXPORT) from exc
    with archive:
        yield _survey(archive)

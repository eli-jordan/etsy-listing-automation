"""restic-shaped repository folders without restic (workspace-backup spec,
*Copy to destinations*).

Every file but ``config`` is named after the SHA-256 of its bytes, as
restic names them, in restic's layout: ``config``, ``keys/``,
``data/<2 hex>/``, ``index/``, ``snapshots/``. The bytes are plain text, so
an index here simply lists the packs it names, and a test can check that a
destination never holds an index whose packs are missing.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileIdentity:
    """Which file is at a path: a replaced file has a new id or mtime."""

    device: int
    inode: int
    mtime_ns: int


def identity(path: Path) -> FileIdentity:
    stat = path.stat()
    return FileIdentity(stat.st_dev, stat.st_ino, stat.st_mtime_ns)


def identities(root: Path) -> dict[str, FileIdentity]:
    return {name: identity(root / name) for name in files(root)}


def files(root: Path) -> dict[str, bytes]:
    """Every file under ``root`` by its ``/`` path."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _named(folder: Path, content: bytes, *, fan_out: bool = False) -> str:
    name = hashlib.sha256(content).hexdigest()
    target = folder / name[:2] if fan_out else folder
    target.mkdir(parents=True, exist_ok=True)
    (target / name).write_bytes(content)
    return name


class FakeRepository:
    """A repository folder a test grows the way restic would."""

    def __init__(self, root: Path, *, repository_id: str = "fake") -> None:
        """``repository_id`` tells two repositories' ``config`` apart."""
        self.root = root
        root.mkdir(parents=True)
        config = {"version": 2, "id": repository_id}
        (root / "config").write_bytes(json.dumps(config).encode())
        _named(root / "keys", b"key: correct horse")
        (root / "locks").mkdir()

    def pack(self, content: bytes) -> str:
        name = _named(self.root / "data", b"pack:" + content, fan_out=True)
        return f"data/{name[:2]}/{name}"

    def index(self, *packs: str) -> str:
        return "index/" + _named(self.root / "index", json.dumps(sorted(packs)).encode())

    def snapshot(self, label: str) -> str:
        return "snapshots/" + _named(self.root / "snapshots", f"snapshot {label}".encode())

    def backup(self, label: str) -> tuple[str, str, str]:
        """A pack, the index naming it and a snapshot: one restic backup."""
        pack = self.pack(label.encode())
        return pack, self.index(pack), self.snapshot(label)

    def remove(self, *names: str) -> None:
        for name in names:
            (self.root / name).unlink()


def missing_packs(root: Path) -> set[str]:
    """Packs an index in ``root`` names that ``root`` lacks."""
    named: set[str] = set()
    for index in (root / "index").glob("*"):
        named.update(json.loads(index.read_bytes()))
    return {pack for pack in named if not (root / pack).is_file()}

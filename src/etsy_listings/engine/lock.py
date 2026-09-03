"""``state.lock.json``: the verbatim last-applied desired document. A2.

Hashing rules, enforced by the single :func:`canonical_hash` helper every stage
must go through: hash only the ``applied`` subtree; ``applied_at``,
``tool_version``, ``remote`` and absolute paths are excluded. Paths inside hashed
content are always workspace-relative and forward-slashed -- non-negotiable on
Windows, where the same content would otherwise hash differently than on Linux.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

from pydantic import BaseModel, ConfigDict

SCHEMA_VERSION = 1


def to_workspace_relative_posix(root: Path, path: Path) -> str:
    """Render ``path`` as a forward-slashed string relative to ``root``.

    Every path that enters a hash must go through this -- a bare ``str(Path)``
    on Windows would use backslashes and hash differently than the same content
    hashed on Linux, silently breaking every cross-machine comparison.
    """
    relative = path.resolve().relative_to(root.resolve())
    return str(PurePosixPath(relative.as_posix()))


def canonical_hash(applied: dict[str, Any]) -> str:
    """Hash the ``applied`` subtree only. Deterministic: key order, whitespace and
    float formatting cannot change the result for equal content."""
    canonical = json.dumps(applied, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


class Lockfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    tool_version: str
    applied_at: str

    applied: dict[str, Any] = {}
    remote: dict[str, Any] = {}
    outputs: dict[str, str] = {}
    stages_completed: list[str] = []

    def input_hash(self) -> str:
        return canonical_hash(self.applied)

    @classmethod
    def empty(cls, *, tool_version: str, applied_at: str) -> Lockfile:
        return cls(tool_version=tool_version, applied_at=applied_at)

    @classmethod
    def read(cls, path: Path) -> Lockfile | None:
        if not path.is_file():
            return None
        return cls.model_validate_json(path.read_text(encoding="utf-8"))

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(path)

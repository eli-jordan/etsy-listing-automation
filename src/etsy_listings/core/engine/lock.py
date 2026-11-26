from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, ValidationError

AppliedT = TypeVar("AppliedT", bound=BaseModel)
"""A stage's applied document. Always a model, never a dict: that is what
makes :meth:`Lockfile.parse_applied_for` able to own the decode rule for every
stage rather than each stage owning a copy of it."""

SCHEMA_VERSION = 1

HASH_PREFIX = "sha256:"
SHORT_DIGEST_LENGTH = 12
"""Hex digits a plan shows of a content hash: enough to tell two files apart."""


def short_digest(content_hash: str) -> str:
    return content_hash.removeprefix(HASH_PREFIX)[:SHORT_DIGEST_LENGTH]


def to_workspace_relative_posix(root: Path, path: Path) -> str:
    relative = path.resolve().relative_to(root.resolve())
    return str(PurePosixPath(relative.as_posix()))


def hash_file(path: Path) -> str:
    return hash_bytes(path.read_bytes())


def hash_bytes(data: bytes) -> str:
    return f"{HASH_PREFIX}{hashlib.sha256(data).hexdigest()}"


def canonical_hash(applied: dict[str, Any]) -> str:
    canonical = json.dumps(applied, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{HASH_PREFIX}{digest}"


@dataclass(frozen=True)
class StageApplyResult:
    applied: dict[str, Any]
    outputs: dict[str, str] = field(default_factory=dict)
    remote: dict[str, Any] = field(default_factory=dict)


class IncompleteApply(BaseModel):
    model_config = ConfigDict(extra="forbid")

    stage: str


class Lockfile(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = SCHEMA_VERSION
    tool_version: str
    applied_at: str

    applied: dict[str, Any] = {}
    remote: dict[str, Any] = {}
    outputs: dict[str, str] = {}
    stages_completed: list[str] = []
    incomplete: IncompleteApply | None = None
    """Set by :meth:`marked_incomplete`, cleared by :meth:`completed` -- never
    by hand elsewhere."""

    def input_hash(self) -> str:
        return canonical_hash(self.applied)

    def applied_for(self, stage: str) -> dict[str, Any] | None:
        data: dict[str, Any] | None = self.applied.get(stage)
        return data

    def parse_applied_for(self, stage: str, model: type[AppliedT]) -> AppliedT | None:
        data = self.applied_for(stage)
        if data is None:
            return None
        try:
            return model.model_validate(data)
        except ValidationError:
            return None

    def fold(self, stage: str, result: StageApplyResult) -> Lockfile:
        completed = list(self.stages_completed)
        if stage not in completed:
            completed.append(stage)
        return self.model_copy(
            update={
                "applied": {**self.applied, stage: result.applied},
                "outputs": {**self.outputs, **result.outputs},
                "remote": {**self.remote, **result.remote},
                "stages_completed": completed,
            }
        )

    def marked_incomplete(self, stage: str) -> Lockfile:
        return self.model_copy(update={"incomplete": IncompleteApply(stage=stage)})

    def completed(self) -> Lockfile:
        return self.model_copy(update={"incomplete": None})

    def stamped(self, *, tool_version: str, applied_at: str) -> Lockfile:
        return self.model_copy(update={"tool_version": tool_version, "applied_at": applied_at})

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
        tmp.write_text(self.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
        tmp.replace(path)

"""``state.lock.json``: the verbatim last-applied desired document. A2.

Hashing rules, enforced by the single :func:`canonical_hash` helper every stage
must go through: hash only the ``applied`` subtree; ``applied_at``,
``tool_version``, ``remote`` and absolute paths are excluded. Paths inside hashed
content are always workspace-relative and forward-slashed -- non-negotiable on
Windows, where the same content would otherwise hash differently than on Linux.

**This module owns the merge, not just the file.** The four axes a stage can
write to used to be public dicts that ``apply`` copied and combined by hand,
with the rules for doing so written down one module away, in
:class:`StageApplyResult`'s docstring. Rules stated in one place and
implemented in another are rules that drift, so :meth:`Lockfile.fold` is now
where a stage's result becomes the next lockfile, and
:meth:`Lockfile.applied_for` is where a stage gets its own subtree back --
which is what lets the ``Stage`` protocol drop a method (A2, A20).
"""

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


def to_workspace_relative_posix(root: Path, path: Path) -> str:
    """Render ``path`` as a forward-slashed string relative to ``root``.

    Every path that enters a hash must go through this -- a bare ``str(Path)``
    on Windows would use backslashes and hash differently than the same content
    hashed on Linux, silently breaking every cross-machine comparison.
    """
    relative = path.resolve().relative_to(root.resolve())
    return str(PurePosixPath(relative.as_posix()))


def hash_file(path: Path) -> str:
    """Hash a file's raw bytes.

    The *other* hash axis. :func:`canonical_hash` answers "would this document
    produce a different result?"; this answers "did this file change?" -- and
    it is deliberately the bytes rather than anything decoded from them, so an
    edit a parser would round-trip away still counts as a change.

    One helper rather than one per stage: the render stage hashes designs,
    ``template.yaml`` and mockup photos, the product stage hashes the same
    designs again as its print files, and two spellings of ``sha256:`` + a
    digest is two chances for the prefix to differ and every listing to show a
    diff.
    """
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def canonical_hash(applied: dict[str, Any]) -> str:
    """Hash the ``applied`` subtree only. Deterministic: key order, whitespace and
    float formatting cannot change the result for equal content."""
    canonical = json.dumps(applied, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


@dataclass(frozen=True)
class StageApplyResult:
    """What a stage's ``apply`` hands back to fold into the next lockfile.

    Three dicts, each merged into a different part of it by
    :meth:`Lockfile.fold` -- never by the stage, which returns a value and lets
    the lockfile decide what becomes of it. That is what keeps a stage testable
    without a lockfile.

    It lives beside the file it is folded into rather than beside the protocol
    that returns it: every rule below is a rule about ``state.lock.json``, and
    they were previously documented here and implemented a module away.

    ``applied`` becomes ``lock.applied[stage]`` -- the verbatim last-applied
    document A2 hashes. ``outputs`` merges into the lockfile's separate
    ``outputs`` axis (workspace-relative path -> content hash), which is what
    later decides whether a file needs *re-uploading*, independently of
    whether the stage needed to *re-run* at all.

    ``remote`` merges into ``lock.remote``: ids an API handed back, which the
    stage did not choose and cannot derive (A20). Each stage owns a key prefix
    -- ``printify_*``, ``etsy_*`` -- so one arriving never displaces another's.

    **``remote`` is never hashed**, and that is the point of keeping it out of
    ``applied`` rather than letting a stage tuck ids in there. A product id is
    volatile by definition; hash one and every listing shows a diff for the
    rest of its life. ``canonical_hash`` only sees the ``applied`` subtree, so
    the separation is enforced by the lockfile rather than by convention.
    """

    applied: dict[str, Any]
    outputs: dict[str, str] = field(default_factory=dict)
    remote: dict[str, Any] = field(default_factory=dict)


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

    def applied_for(self, stage: str) -> dict[str, Any] | None:
        """One stage's last-applied document, or ``None`` if it has never run.

        The lookup every stage used to write for itself as
        ``lock.applied.get(self.name)``. Doing it here is what lets the
        ``Stage`` protocol drop its ``last_applied`` method: a stage is handed
        its own subtree and parses it, instead of being handed the whole
        lockfile and trusted to take only its own key out of it.
        """
        data: dict[str, Any] | None = self.applied.get(stage)
        return data

    def parse_applied_for(self, stage: str, model: type[AppliedT]) -> AppliedT | None:
        """One stage's last-applied document, as the type that stage reads it as.

        The rule, written once. ``None`` in, ``None`` out -- a stage that has
        never run has no applied document. A document that will not *decode*
        answers ``None`` as well, and that is a reading rather than a
        swallowed error: a document we cannot read is one we cannot prove the
        live state matches, which is what "never applied" already means. The
        cost is redoing work that was probably already done; the alternative
        is `plan` dying on a lockfile some other version wrote.

        It was written twice, and the copies disagreed. The product stage
        caught ``ValidationError`` and answered ``None``; the render stage
        indexed ``data["input_hash"]`` and raised ``KeyError`` -- which is not
        a :class:`~etsy_listings.errors.UserFacingError`, so a single
        truncated lockfile ended a whole ``--all`` batch with a traceback.
        Neither stage decides this any more.
        """
        data = self.applied_for(stage)
        if data is None:
            return None
        try:
            return model.model_validate(data)
        except ValidationError:
            return None

    def fold(self, stage: str, result: StageApplyResult) -> Lockfile:
        """``result`` merged in, as a new lockfile.

        One rule per axis, and each used to be a line in ``execute``'s loop:
        ``applied`` is **replaced** for this stage, ``outputs`` and ``remote``
        **merge** by key, and ``stages_completed`` gains the stage once.

        Replace-versus-merge is the distinction worth stating.
        ``applied[stage]`` is a whole document, so a stage that stops emitting
        a field must not keep the old one. ``remote`` is shared *across*
        stages, so a Printify id arriving must not take the Etsy listing id
        with it (A20) -- it merges.
        """
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

    def stamped(self, *, tool_version: str, applied_at: str) -> Lockfile:
        """The same content, marked with what wrote it and when.

        Separate from :meth:`fold` because it happens once per run rather than
        once per stage -- and because neither field may ever enter a hash
        (A2), so the one place they are set is the one place to look to check
        that they have not.
        """
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
        tmp.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(path)

"""Renaming a mockup template, and everything that follows it.

A template's name is its directory, and nothing else identifies it, so a move
alone would leave every reference pointing at a folder that is gone. The
directory goes first, because it is the one step that can fail for reasons a
retry fixes (a photo open elsewhere, a taken name), and at that point nothing
has changed. Then, in the order that keeps a batch from making a listing out
of a stale frozen document:

1. batch and staging records, whose frozen documents name the template;
2. listing templates and garment profiles;
3. each listing: its ``listing.yaml``, its render and preview caches, and the
   Etsy image refs in its lockfile (:mod:`~etsy_listings.core.engine.template_refs`).

Marigold maps live inside the directory and are template-relative, so they
move with it and stay valid; the preparation queue brings its own records
(:meth:`Preparations.rename_template`).

Every reference file is tried, and one that cannot be read or written is
reported rather than stopping the rest: by then the directory has moved, so
stopping would only leave more to fix by hand. A rename does not touch the
photos, whose filenames may carry any prefix (ADR-0004).

The template's lock covers only the move. It is not held across the listing
edits, because a listing's lock is taken first everywhere else. The check for
active deploys is a check, not a lock: the second-process caveat in
:mod:`etsy_listings.core.workspace.locks` applies here too.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import yaml

from etsy_listings.core.application.mockup_templates import require_template
from etsy_listings.core.application.refusals import TemplateInUseError, TemplateNameTakenError
from etsy_listings.core.batches.records import BatchRecords
from etsy_listings.core.config.template_refs import rename_template_refs
from etsy_listings.core.engine.template_refs import follow_template_rename
from etsy_listings.core.workspace import locks
from etsy_listings.core.workspace.atomic import read_bytes_retrying, write_yaml_atomic
from etsy_listings.core.workspace.listing_documents import ListingDocuments
from etsy_listings.core.workspace.trees import remove_tree
from etsy_listings.core.workspace.workspace import InvalidNameError, Workspace
from etsy_listings.core.workspace.yaml_source import UneditableYamlError

_UNUPDATABLE = (OSError, ValueError, yaml.YAMLError, UneditableYamlError)
"""What one reference file can answer with: unreadable, unparsable, an
undecodable lockfile, or YAML that cannot be edited in place."""

Change = Callable[[dict[str, Any]], dict[str, Any] | None]


class TemplateMover(Protocol):
    """The preparation queue's side of a rename."""

    def rename_template(self, old: str, new: str, move: Callable[[], None]) -> None: ...


@dataclass(frozen=True)
class RenameHosts:
    """What a rename asks of the running process."""

    preparations: TemplateMover
    records: BatchRecords
    deploying: Callable[[], bool]


@dataclass(frozen=True)
class TemplateRename:
    """What followed a rename, as workspace-relative files. ``unresolved`` may
    still name the old template, and the seller has to look at them."""

    updated: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()


@dataclass
class _Outcome:
    updated: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)


def rename_template(workspace: Workspace, old: str, new: str, hosts: RenameHosts) -> TemplateRename:
    """Move mockup template ``old``, and everything naming it, to ``new``.

    Renaming to the same name changes nothing. Refusals, all before anything
    changes: ``InvalidNameError``, :class:`TemplateMissingError`,
    :class:`TemplateNameTakenError`, and :class:`TemplateInUseError` while a
    deploy runs, while the template is being prepared, or while Windows holds
    one of its files open.
    """
    require_template(workspace, old)
    destination = workspace.template_dir(new)
    if new != new.strip(" ."):  # Windows drops these, so the refs would not match the folder.
        raise InvalidNameError(new)
    if new == old:
        return TemplateRename()
    if hosts.deploying():
        raise TemplateInUseError("A deploy is running; rename the template when it finishes")
    hosts.preparations.rename_template(old, new, lambda: _move(workspace, old, new, destination))
    hosts.records.rename_mockup_template(old, new)
    outcome = _Outcome()
    _follow_listing_templates(workspace, old, new, outcome)
    _follow_garment_profiles(workspace, old, new, outcome)
    _follow_listings(workspace, old, new, outcome)
    return TemplateRename(tuple(outcome.updated), tuple(outcome.unresolved))


def _move(workspace: Workspace, old: str, new: str, destination: Path) -> None:
    """Under both templates' locks. A name Windows will not take surfaces only
    here, as an ``OSError`` that is not about permissions."""
    require_template(workspace, old)
    if destination.exists():
        raise TemplateNameTakenError(new)
    try:
        workspace.template_dir(old).rename(destination)
    except PermissionError as exc:
        raise TemplateInUseError(f"A file in {old!r} is open; try again in a moment") from exc
    except OSError as exc:
        raise InvalidNameError(new) from exc


def _follow_listing_templates(workspace: Workspace, old: str, new: str, outcome: _Outcome) -> None:
    for name in workspace.listing_template_names():
        with locks.hold(workspace, "listing-template", name):
            _follow_file(
                workspace,
                workspace.listing_template_file(name),
                lambda document: rename_template_refs(document, old, new),
                outcome,
            )


def _follow_garment_profiles(workspace: Workspace, old: str, new: str, outcome: _Outcome) -> None:
    def change(document: dict[str, Any]) -> dict[str, Any] | None:
        if document.get("preview_template") != old:
            return None
        return {**document, "preview_template": new}

    for name in workspace.garment_profile_names():
        _follow_file(workspace, workspace.garment_profile_file(name), change, outcome)


def _follow_file(workspace: Workspace, path: Path, change: Change, outcome: _Outcome) -> None:
    """``path``'s references, edited in place (ADR-0055). The caller holds
    whatever lock guards it."""
    relative = workspace.relative_path(path)
    try:
        document = yaml.safe_load(read_bytes_retrying(path))
        changed = change(document) if isinstance(document, dict) else None
        if changed is None:
            return
        write_yaml_atomic(path, changed, new=lambda: yaml.safe_dump(changed, sort_keys=False))
    except _UNUPDATABLE:
        outcome.unresolved.append(relative)
    else:
        outcome.updated.append(relative)


def _follow_listings(workspace: Workspace, old: str, new: str, outcome: _Outcome) -> None:
    documents = ListingDocuments(workspace)
    for listing in workspace.listing_names():
        relative = workspace.relative_path(workspace.listing_file(listing))
        try:
            with documents.lock(listing):
                updated = _follow_listing(workspace, documents, listing, old, new)
        except _UNUPDATABLE:
            outcome.unresolved.append(relative)
        else:
            if updated:
                outcome.updated.append(relative)


def _follow_listing(
    workspace: Workspace, documents: ListingDocuments, listing: str, old: str, new: str
) -> bool:
    """Under the listing's lock; whether ``listing.yaml`` changed. A listing
    awaiting retraction may have only a lockfile, which follows all the same."""
    written = None
    if documents.exists(listing):
        written = documents.edit(listing, lambda document: rename_template_refs(document, old, new))
    sources = workspace.listing_template_caches(listing, old)
    targets = workspace.listing_template_caches(listing, new)
    for source, target in zip(sources, targets, strict=True):
        if source.is_dir():
            if target.is_dir():
                remove_tree(target)
            source.replace(target)
    follow_template_rename(workspace, listing, old, new)
    return written is not None

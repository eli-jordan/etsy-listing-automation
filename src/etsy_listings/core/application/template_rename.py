"""Renaming a mockup template and every listing and lockfile that names it.

The template's lock covers only the move, not the listing edits, because a
listing's lock is taken first everywhere else."""

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
from etsy_listings.core.engine.template_refs import follow_template_rename_locked
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
    def rename_template(self, old: str, new: str, move: Callable[[], None]) -> None: ...


@dataclass(frozen=True)
class RenameHosts:
    preparations: TemplateMover
    records: BatchRecords
    deploying: Callable[[], bool]


@dataclass(frozen=True)
class TemplateRename:
    updated: tuple[str, ...] = ()
    unresolved: tuple[str, ...] = ()


@dataclass
class _Outcome:
    updated: list[str] = field(default_factory=list)
    unresolved: list[str] = field(default_factory=list)


def rename_template(workspace: Workspace, old: str, new: str, hosts: RenameHosts) -> TemplateRename:
    require_template(workspace, old)
    destination = workspace.template_dir(new)
    if new != new.strip(" ."):  # Windows drops these, so the refs would not match the folder.
        raise InvalidNameError(new)
    if new == old:
        return TemplateRename()
    if hosts.deploying():
        raise TemplateInUseError("A deploy is running; rename the template when it finishes")
    hosts.preparations.rename_template(
        old, new, lambda: _move_locked(workspace, old, new, destination)
    )
    hosts.records.rename_mockup_template(old, new)
    outcome = _Outcome()
    _follow_listing_templates(workspace, old, new, outcome)
    _follow_garment_profiles(workspace, old, new, outcome)
    _follow_listings(workspace, old, new, outcome)
    return TemplateRename(tuple(outcome.updated), tuple(outcome.unresolved))


def _move_locked(workspace: Workspace, old: str, new: str, destination: Path) -> None:
    """A name Windows refuses surfaces only here, as a non-permission ``OSError``."""
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
                updated = _follow_listing_locked(workspace, documents, listing, old, new)
        except _UNUPDATABLE:
            outcome.unresolved.append(relative)
        else:
            if updated:
                outcome.updated.append(relative)


def _follow_listing_locked(
    workspace: Workspace, documents: ListingDocuments, listing: str, old: str, new: str
) -> bool:
    """A listing awaiting retraction may be only a lockfile."""
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
    follow_template_rename_locked(workspace, listing, old, new)
    return written is not None

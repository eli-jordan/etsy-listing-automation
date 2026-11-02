"""What saving candidate template position limits would change, before it is
saved: the question Settings' confirmation answers (template positions PR 5;
interactions, *Settings: Template rendering*).

Two lists, read off the workspace as it is now and writing nothing:

- ``outside``: each listing whose saved positions the candidate limits would
  refuse on scale, offset or rotation, with the refused keys
  (``listing_validation.positions_outside_limits``). Listings already blocked
  for another reason, or that do not load, are not listed.
- ``refit``: the Marigold templates whose maps a save would refit. Empty
  while spec rule 5 refuses Marigold positions; PR 7 pads Marigold maps to the
  limits and fills it with every Marigold template.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import ValidationError

from etsy_listings.core.application.refusals import InvalidSettingsEditError, field_errors_of
from etsy_listings.core.config.errors import ConfigLoadError
from etsy_listings.core.config.listing_validation import positions_outside_limits
from etsy_listings.core.config.settings import Settings, TemplatePositionLimits
from etsy_listings.core.render.config import AnyTemplate
from etsy_listings.core.workspace.workspace import Workspace


@dataclass(frozen=True)
class ListingOutside:
    listing: str
    positions: tuple[str, ...]
    """Dotted ``template_positions`` keys, placements included."""


@dataclass(frozen=True)
class LimitsImpact:
    outside: tuple[ListingOutside, ...]
    refit: tuple[str, ...]
    """Marigold template names; empty until Marigold positions ship (PR 7)."""


def candidate_limits(limits: Mapping[str, object]) -> TemplatePositionLimits:
    """``limits`` validated as the save would validate them, refused naming
    the same ``template_positions.*`` keys."""
    try:
        return Settings.model_validate({"template_positions": dict(limits)}).template_positions
    except ValidationError as exc:
        raise InvalidSettingsEditError(field_errors_of(exc)) from exc


def template_position_impact(workspace: Workspace, limits: TemplatePositionLimits) -> LimitsImpact:
    """Who ``limits`` would block, and what they would refit."""
    templates = _TemplateCache(workspace)
    outside = []
    for name in workspace.listing_names():
        try:
            listing = workspace.load_listing(name)
        except ConfigLoadError:
            continue
        if not listing.template_positions:
            continue
        keys = positions_outside_limits(
            listing, templates.named(listing.template_positions), limits
        )
        if keys:
            outside.append(ListingOutside(name, tuple(keys)))
    return LimitsImpact(outside=tuple(outside), refit=())


class _TemplateCache:
    """Template configs loaded once each, only for templates a listing names."""

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace
        self._available = set(workspace.template_names())
        self._loaded: dict[str, AnyTemplate | None] = {}

    def named(self, names: Mapping[str, object]) -> dict[str, AnyTemplate]:
        configs = {name: self._config(name) for name in names}
        return {name: config for name, config in configs.items() if config is not None}

    def _config(self, name: str) -> AnyTemplate | None:
        if name not in self._loaded:
            self._loaded[name] = self._load(name)
        return self._loaded[name]

    def _load(self, name: str) -> AnyTemplate | None:
        if name not in self._available:
            return None
        try:
            return self._workspace.load_template_config(name)
        except ConfigLoadError:
            return None

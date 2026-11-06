"""What saving candidate template position limits would change, before it is
saved: the question Settings' confirmation answers (template positions PR 5;
interactions, *Settings: Template rendering*; option B, spec *Marigold*).

Two lists, read off the workspace as it is now and writing nothing:

- ``outside``: each listing whose saved positions the candidate limits would
  refuse on scale, offset or rotation, with the refused keys
  (``listing_validation.positions_outside_limits``). Listings already blocked
  for another reason, or that do not load, are not listed.
- ``templates_needing_inference``: the Marigold templates whose preparation
  evidence would need model inference to cover the wider limits: those a
  listing positions whose evidence misses the candidate padded quad
  (``position_coverage.templates_needing_coverage``, PR 7b). Saving them
  queues that inference; narrowing never adds to it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from pydantic import ValidationError

from etsy_listings.core.application.position_coverage import templates_needing_coverage
from etsy_listings.core.application.refusals import InvalidSettingsEditError, field_errors_of
from etsy_listings.core.config.errors import ConfigLoadError
from etsy_listings.core.config.listing_validation import positions_outside_limits
from etsy_listings.core.config.settings import Settings, TemplatePositionLimits
from etsy_listings.core.render.config import AnyTemplate
from etsy_listings.core.workspace.template_state import template_state
from etsy_listings.core.workspace.workspace import Workspace


@dataclass(frozen=True)
class ListingOutside:
    listing: str
    positions: tuple[str, ...]
    """Dotted ``template_positions`` keys, placements included."""


@dataclass(frozen=True)
class LimitsImpact:
    outside: tuple[ListingOutside, ...]
    templates_needing_inference: tuple[str, ...]
    """Marigold template names, sorted; empty unless the limits widen."""


def candidate_limits(limits: Mapping[str, object]) -> TemplatePositionLimits:
    """``limits`` validated as the save would validate them, refused naming
    the same ``template_positions.*`` keys."""
    try:
        return Settings.model_validate({"template_positions": dict(limits)}).template_positions
    except ValidationError as exc:
        raise InvalidSettingsEditError(field_errors_of(exc)) from exc


def template_position_impact(workspace: Workspace, limits: TemplatePositionLimits) -> LimitsImpact:
    """Who ``limits`` would block, and which templates would need inference.
    Raises :class:`ConfigLoadError` when the saved ``settings.yaml`` does not load."""
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
    saved = workspace.load_settings().template_positions
    return LimitsImpact(
        outside=tuple(outside),
        templates_needing_inference=tuple(templates_needing_coverage(workspace, limits, saved)),
    )


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
        return template_state(self._workspace, name).config

"""Prune position fits no listing references (spec *Rendering → Marigold
(option B)*: "Fits no listing references are pruned with the cache").

A fit is kept while some listing's saved position, against its template's
*current* saved inputs and evidence, produces its key -- exactly the key
``lease_scene`` would ask for. Fits of an old geometry, mask or evidence are
therefore removed once nothing produces them; they are rebuildable from
evidence. :meth:`PositionFits.prune` spares fits being written or leased by a
scene, and anything stored after the scan began.

The scene warmer runs this at startup and each time its queue drains, so a
saved position change prunes the fit it replaced.
"""

from __future__ import annotations

import logging

from etsy_listings.core.config.errors import ConfigLoadError
from etsy_listings.core.config.template_positions import TemplatePositions, layer_boxes
from etsy_listings.core.errors import UserFacingError
from etsy_listings.core.preparation.artifacts import Artifacts, PreparationInputs
from etsy_listings.core.preparation.position_fits import (
    PositionFits,
    positioned_quads,
    scan_started,
)
from etsy_listings.core.render.config import AnyTemplate, MarigoldRenderer
from etsy_listings.core.workspace.template_state import template_state
from etsy_listings.core.workspace.workspace import Workspace

logger = logging.getLogger(__name__)


def prune_position_fits(workspace: Workspace) -> list[str]:
    """Remove the fits no listing's current position produces; the removed
    keys. Nothing is removed when the workspace cannot be read reliably."""
    if not workspace.position_fits():
        return []
    fits = PositionFits(workspace)
    since = scan_started()
    try:
        keep = _referenced(workspace, fits)
    except OSError as exc:
        logger.warning("not pruning position fits: %s", exc)
        return []
    return fits.prune(keep, since=since)


def _referenced(workspace: Workspace, fits: PositionFits) -> set[str]:
    """The keys every loadable listing's saved positions produce now."""
    templates = _Templates(workspace)
    keep: set[str] = set()
    for name in workspace.listing_names():
        try:
            positions = workspace.load_listing(name).template_positions or {}
        except ConfigLoadError:
            continue
        for template in positions:
            keep.update(_keys(fits, templates, positions, template))
    return keep


def _keys(
    fits: PositionFits, templates: _Templates, positions: TemplatePositions, template: str
) -> set[str]:
    loaded = templates.get(template)
    if loaded is None:
        return set()
    config, inputs = loaded
    quads = positioned_quads(config, layer_boxes(positions, template))
    try:
        requests = fits.requests(template, inputs, quads)
    except (UserFacingError, ValueError) as exc:
        # Uncovered evidence: no current fit exists to keep.
        logger.debug("no current fit on %r: %s", template, exc)
        return set()
    return {request.key for request in requests.values()}


class _Templates:
    """Each Marigold template's config and saved inputs, read once."""

    def __init__(self, workspace: Workspace) -> None:
        self._workspace = workspace
        self._loaded: dict[str, tuple[AnyTemplate, PreparationInputs] | None] = {}

    def get(self, name: str) -> tuple[AnyTemplate, PreparationInputs] | None:
        if name not in self._loaded:
            self._loaded[name] = _template(self._workspace, name)
        return self._loaded[name]


def _template(workspace: Workspace, name: str) -> tuple[AnyTemplate, PreparationInputs] | None:
    """A Marigold template's config and saved inputs, or None when it is not
    Marigold or does not load (its listings then keep no fit)."""
    try:
        config = template_state(workspace, name).require()
        if not isinstance(config.renderer, MarigoldRenderer):
            return None
        return config, Artifacts(workspace).saved_inputs(name)
    except (UserFacingError, ValueError) as exc:
        logger.debug("template %r keeps no fits: %s", name, exc)
        return None

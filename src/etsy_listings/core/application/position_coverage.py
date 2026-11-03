"""Queue the inference Marigold listing positions need (option B).

A listing position on a Marigold template is fitted from evidence covering
the template's padded quad (spec *Rendering → Marigold (option B: a fit per
position)*, *Evidence coverage*). Three explicit seller actions queue coverage
inference for a template whose evidence falls short (ADR-0058, amendment
*Marigold positions and inference*):

- saving a position on it (:func:`cover_listing_positions`);
- confirming wider limits in Settings (:func:`cover_widened_limits`), for the
  templates :func:`templates_needing_coverage` named in the confirmation;
- saving its geometry in the calibrator while a listing positions it
  (:func:`cover_recalibrated`).

A covered template needs nothing here, since the scene warmer fits the
position itself. Narrowing the limits queues nothing: evidence that reached
the wider padded quad reaches the narrower one (spec *Limits changes*).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable

from etsy_listings.core.application.preparation.coordinator import Preparations
from etsy_listings.core.application.preparation.models import Job
from etsy_listings.core.config.errors import ConfigLoadError
from etsy_listings.core.errors import UserFacingError
from etsy_listings.core.preparation.artifacts import Artifacts
from etsy_listings.core.preparation.position_fits import PositionFits, padded_quads
from etsy_listings.core.render.config import MarigoldRenderer
from etsy_listings.core.render.positions import PositionLimits
from etsy_listings.core.workspace.workspace import Workspace

logger = logging.getLogger(__name__)

_SKIPPED = (UserFacingError, ValueError, OSError)


def widens(candidate: PositionLimits, saved: PositionLimits) -> bool:
    """Whether ``candidate`` allows any pose ``saved`` does not: the only
    change that can need new inference."""
    return (
        candidate.scale.min < saved.scale.min
        or candidate.scale.max > saved.scale.max
        or candidate.offset > saved.offset
        or candidate.rotation > saved.rotation
    )


def positioned_templates(workspace: Workspace) -> list[str]:
    """Every template a loadable listing holds a position for, sorted."""
    names: set[str] = set()
    for listing in workspace.listing_names():
        try:
            names.update(workspace.load_listing(listing).template_positions or {})
        except ConfigLoadError:
            continue
    return sorted(names)


def needs_coverage(workspace: Workspace, template: str, limits: PositionLimits) -> bool:
    """Whether ``template`` is Marigold and its current evidence misses its
    padded quad under ``limits``: what :meth:`Preparations.cover` would infer.
    A template that cannot be read is not counted; ``plan`` reports it."""
    try:
        config = workspace.load_template_config(template)
        if not isinstance(config.renderer, MarigoldRenderer):
            return False
        padded = padded_quads(config, limits)
        if padded is None:
            return False
        inputs = Artifacts(workspace).saved_inputs(template)
        return not PositionFits(workspace).covers(template, inputs, padded)
    except _SKIPPED as exc:
        logger.debug("not checking %r's coverage: %s", template, exc)
        return False


def templates_needing_coverage(
    workspace: Workspace, candidate: PositionLimits, saved: PositionLimits
) -> list[str]:
    """The positioned Marigold templates saving ``candidate`` over ``saved``
    would queue inference for; none unless ``candidate`` widens ``saved``."""
    if not widens(candidate, saved):
        return []
    return [
        name
        for name in positioned_templates(workspace)
        if needs_coverage(workspace, name, candidate)
    ]


def cover_listing_positions(preparations: Preparations, name: str) -> list[Job]:
    """The coverage jobs queued or joined for listing ``name``'s saved
    positions, at the workspace's current limits. A template that cannot be
    read or prepared is skipped: ``plan`` and the preview report it."""
    workspace = preparations.workspace
    try:
        positions = workspace.load_listing(name).template_positions or {}
        limits = workspace.load_settings().template_positions
    except _SKIPPED as exc:
        logger.debug("not covering listing %r's positions: %s", name, exc)
        return []
    return _cover(preparations, positions, limits)


def cover_widened_limits(
    preparations: Preparations, saved: PositionLimits, limits: PositionLimits
) -> list[Job]:
    """After ``limits`` replaced ``saved``: coverage jobs for every positioned
    template whose evidence misses the wider padded quads; none on narrowing."""
    if not widens(limits, saved):
        return []
    return _cover(preparations, positioned_templates(preparations.workspace), limits)


def cover_recalibrated(preparations: Preparations, template: str) -> list[Job]:
    """After ``template``'s calibration saved: its coverage job when a listing
    positions it and its new padded quad is not covered (spec
    *Recalibration*). Fits of the old geometry are keyed by it, so they are
    refitted on demand and pruned once unreferenced."""
    workspace = preparations.workspace
    if template not in positioned_templates(workspace):
        return []
    try:
        limits = workspace.load_settings().template_positions
    except _SKIPPED as exc:
        logger.debug("not covering recalibrated %r: %s", template, exc)
        return []
    return _cover(preparations, [template], limits)


def _cover(
    preparations: Preparations, templates: Iterable[str], limits: PositionLimits
) -> list[Job]:
    jobs = []
    for template in templates:
        try:
            job = preparations.cover(template, limits)
        except _SKIPPED as exc:
            logger.debug("not covering %r: %s", template, exc)
            continue
        if job is not None:
            jobs.append(job)
    return jobs

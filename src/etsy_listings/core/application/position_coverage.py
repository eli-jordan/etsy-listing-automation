"""Queue the inference Marigold listing positions need (option B).

A listing position on a Marigold template is fitted from evidence covering
the template's padded quad (spec *Rendering → Marigold (option B: a fit per
position)*, *Evidence coverage*). A finished preparation queues it itself
(ADR-0058, amendment *coverage belongs to preparation*); these explicit seller
actions queue it for a template whose evidence still falls short:

- saving a position on it (:func:`cover_listing_positions`);
- confirming wider limits in Settings (:func:`cover_widened_limits`), for the
  templates :func:`templates_needing_coverage` named in the confirmation;
- saving its geometry in the calibrator while a listing positions it
  (:func:`cover_recalibrated`).
- asking to adjust it in the editor (:func:`cover_template`);
- asking to catch every prepared template up
  (:func:`cover_prepared_templates`).

A covered template needs nothing here, since the scene warmer fits the
position itself. Narrowing the limits queues nothing: evidence that reached
the wider padded quad reaches the narrower one (spec *Limits changes*).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from etsy_listings.core.application.preparation.coordinator import (
    MAX_JOB_PAGE,
    Preparations,
)
from etsy_listings.core.application.preparation.models import TERMINAL, Job
from etsy_listings.core.config.errors import ConfigLoadError
from etsy_listings.core.errors import UserFacingError
from etsy_listings.core.preparation.artifacts import Artifacts
from etsy_listings.core.preparation.position_fits import PositionFits, padded_quads
from etsy_listings.core.preparation.readiness import template_readiness
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


def needs_coverage(
    workspace: Workspace, template: str, limits: PositionLimits, *, verify: bool = True
) -> bool:
    """Whether ``template`` is Marigold and its current evidence misses its
    padded quad under ``limits``: what :meth:`Preparations.cover` would infer.
    A template that cannot be read is not counted; ``plan`` reports it.
    ``verify=False`` takes the evidence files as sound, for a quick answer."""
    try:
        config = workspace.load_template_config(template)
        if not isinstance(config.renderer, MarigoldRenderer):
            return False
        padded = padded_quads(config, limits)
        if padded is None:
            return False
        inputs = Artifacts(workspace).saved_inputs(template)
        return not PositionFits(workspace).covers(template, inputs, padded, verify=verify)
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


@dataclass(frozen=True)
class PositionReadiness:
    """Whether the editor may adjust a template yet."""

    ready: bool
    preparing: bool
    """A job for it is queued or running, so there is nothing to start."""


def position_readiness(preparations: Preparations, template: str) -> PositionReadiness:
    """``template``'s readiness for positions, quick enough to ask whenever it
    is selected. A template not prepared has its maps to report instead, and
    unreadable settings hold nothing back: ``plan`` reports them."""
    jobs = preparations.list_jobs(template=template, limit=MAX_JOB_PAGE)
    if any(job.phase not in TERMINAL for job in jobs):
        return PositionReadiness(ready=False, preparing=True)
    workspace = preparations.workspace
    try:
        limits = workspace.load_settings().template_positions
    except _SKIPPED as exc:
        logger.debug("not checking %r's coverage: %s", template, exc)
        return PositionReadiness(ready=True, preparing=False)
    short = needs_coverage(workspace, template, limits, verify=False)
    return PositionReadiness(ready=not (short and _prepared(workspace)(template)), preparing=False)


def cover_template(preparations: Preparations, template: str) -> Job | None:
    """The coverage job queued or joined for ``template``, which a seller
    asked to adjust; None when it needs none or no worker is installed."""
    try:
        limits = preparations.workspace.load_settings().template_positions
    except _SKIPPED as exc:
        logger.debug("not covering %r: %s", template, exc)
        return None
    return next(iter(_cover(preparations, [template], limits)), None)


def cover_prepared_templates(preparations: Preparations) -> list[Job]:
    """The coverage jobs queued or joined for every prepared Marigold
    template at the workspace's current limits. A template not prepared yet
    gets coverage when its preparation finishes."""
    workspace = preparations.workspace
    try:
        limits = workspace.load_settings().template_positions
    except _SKIPPED as exc:
        logger.debug("not covering prepared templates: %s", exc)
        return []
    return _cover(preparations, filter(_prepared(workspace), workspace.template_names()), limits)


def _prepared(workspace: Workspace) -> Callable[[str], bool]:
    def prepared(template: str) -> bool:
        try:
            config = workspace.load_template_config(template)
            return (
                isinstance(config.renderer, MarigoldRenderer)
                and template_readiness(workspace, template, config).can_render
            )
        except _SKIPPED as exc:
            logger.debug("not reading %r's preparation: %s", template, exc)
            return False

    return prepared


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

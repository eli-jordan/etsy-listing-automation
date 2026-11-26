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
from etsy_listings.core.workspace.template_state import template_state
from etsy_listings.core.workspace.workspace import Workspace

logger = logging.getLogger(__name__)

_SKIPPED = (UserFacingError, ValueError, OSError)


def widens(candidate: PositionLimits, saved: PositionLimits) -> bool:
    return (
        candidate.scale.min < saved.scale.min
        or candidate.scale.max > saved.scale.max
        or candidate.offset > saved.offset
        or candidate.rotation > saved.rotation
    )


def positioned_templates(workspace: Workspace) -> list[str]:
    names: set[str] = set()
    for listing in workspace.listing_names():
        try:
            names.update(workspace.load_listing(listing).template_positions or {})
        except ConfigLoadError:
            continue
    return sorted(names)


def needs_coverage(
    workspace: Workspace, template: str, limits: PositionLimits, *, verify_evidence: bool = True
) -> bool:
    try:
        config = template_state(workspace, template).require()
        if not isinstance(config.renderer, MarigoldRenderer):
            return False
        padded = padded_quads(config, limits)
        if padded is None:
            return False
        inputs = Artifacts(workspace).saved_inputs(template)
        return not PositionFits(workspace).covers(template, inputs, padded, verify=verify_evidence)
    except _SKIPPED as exc:
        logger.debug("not checking %r's coverage: %s", template, exc)
        return False


def templates_needing_coverage(
    workspace: Workspace, candidate: PositionLimits, saved: PositionLimits
) -> list[str]:
    if not widens(candidate, saved):
        return []
    return [
        name
        for name in positioned_templates(workspace)
        if needs_coverage(workspace, name, candidate)
    ]


def cover_listing_positions(preparations: Preparations, name: str) -> list[Job]:
    workspace = preparations.workspace
    limits = _limits(workspace, f"covering listing {name!r}'s positions")
    if limits is None:
        return []
    try:
        positions = workspace.load_listing(name).template_positions or {}
    except _SKIPPED as exc:
        logger.debug("not covering listing %r's positions: %s", name, exc)
        return []
    return _cover(preparations, positions, limits)


def cover_widened_limits(
    preparations: Preparations, saved: PositionLimits, limits: PositionLimits
) -> list[Job]:
    if not widens(limits, saved):
        return []
    return _cover(preparations, positioned_templates(preparations.workspace), limits)


def cover_recalibrated(preparations: Preparations, template: str) -> list[Job]:
    workspace = preparations.workspace
    if template not in positioned_templates(workspace):
        return []
    limits = _limits(workspace, f"covering recalibrated {template!r}")
    return [] if limits is None else _cover(preparations, [template], limits)


@dataclass(frozen=True)
class PositionReadiness:
    ready: bool
    preparing: bool
    """A job for it is queued or running, so there is nothing to start."""


def position_readiness(preparations: Preparations, template: str) -> PositionReadiness:
    jobs = preparations.list_jobs(template=template, limit=MAX_JOB_PAGE)
    if any(job.phase not in TERMINAL for job in jobs):
        return PositionReadiness(ready=False, preparing=True)
    workspace = preparations.workspace
    limits = _limits(workspace, f"checking {template!r}'s coverage")
    if limits is None:
        return PositionReadiness(ready=True, preparing=False)
    short = needs_coverage(workspace, template, limits, verify_evidence=False)
    return PositionReadiness(ready=not (short and _prepared(workspace)(template)), preparing=False)


def cover_template(preparations: Preparations, template: str) -> Job | None:
    limits = _limits(preparations.workspace, f"covering {template!r}")
    return None if limits is None else next(iter(_cover(preparations, [template], limits)), None)


def cover_prepared_templates(preparations: Preparations) -> list[Job]:
    workspace = preparations.workspace
    limits = _limits(workspace, "covering prepared templates")
    if limits is None:
        return []
    return _cover(preparations, filter(_prepared(workspace), workspace.template_names()), limits)


def _limits(workspace: Workspace, skipping: str) -> PositionLimits | None:
    settings = workspace.settings_if_readable(skipping=skipping)
    return settings.template_positions if settings is not None else None


def _prepared(workspace: Workspace) -> Callable[[str], bool]:
    def prepared(template: str) -> bool:
        try:
            config = template_state(workspace, template).require()
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

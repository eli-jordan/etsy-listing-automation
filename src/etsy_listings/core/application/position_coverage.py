"""Queue the inference a listing's Marigold positions need (option B).

A listing position on a Marigold template is fitted from evidence covering
the template's padded quad (spec *Rendering → Marigold (option B: a fit per
position)*, *Evidence coverage*). Saving a position is the seller's explicit
request for that evidence, so it queues coverage inference for each template
the listing positions whose evidence falls short; a covered template needs
nothing here, since the scene warmer fits the position itself.
"""

from __future__ import annotations

import logging

from etsy_listings.core.application.preparation.coordinator import Preparations
from etsy_listings.core.application.preparation.models import Job
from etsy_listings.core.errors import UserFacingError

logger = logging.getLogger(__name__)


def cover_listing_positions(preparations: Preparations, name: str) -> list[Job]:
    """The coverage jobs queued or joined for listing ``name``'s saved
    positions, at the workspace's current limits. A template that cannot be
    read or prepared is skipped: ``plan`` and the preview report it."""
    workspace = preparations.workspace
    try:
        positions = workspace.load_listing(name).template_positions or {}
        limits = workspace.load_settings().template_positions
    except (UserFacingError, ValueError, OSError) as exc:
        logger.debug("not covering listing %r's positions: %s", name, exc)
        return []
    jobs = []
    for template in positions:
        try:
            job = preparations.cover(template, limits)
        except (UserFacingError, ValueError, OSError) as exc:
            logger.debug("not covering %r for listing %r: %s", template, name, exc)
            continue
        if job is not None:
            jobs.append(job)
    return jobs

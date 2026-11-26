"""Concrete stages, in pipeline order (ADR-0007: order encodes dependency, not a
dependency graph).

Each stage uses what the one before it did this run (ADR-0034's
``lock.remote`` threading): ``Publish`` mints the Etsy listing id
``EtsyListing`` and ``EtsyMedia`` PATCH, and ``EtsyVideos`` follows
``EtsyMedia`` because Etsy places a second video by the image count at attach
time. A stage with no shop id configured reports itself unconfigured rather
than failing.

:data:`STAGES` is the interface. A stage's own types (``RenderDesired`` and
friends) are its business; the engine only ever sees them through the
:class:`~etsy_listings.core.engine.stage.Stage` protocol, with their types erased.
"""

from __future__ import annotations

from collections.abc import Sequence

from etsy_listings.core.engine.stage import AnyStage
from etsy_listings.core.engine.stages.etsy_activate import EtsyActivateStage
from etsy_listings.core.engine.stages.etsy_listing import EtsyListingStage
from etsy_listings.core.engine.stages.etsy_media import EtsyMediaStage
from etsy_listings.core.engine.stages.etsy_videos import EtsyVideosStage
from etsy_listings.core.engine.stages.printify_product import PrintifyProductStage
from etsy_listings.core.engine.stages.publish import PublishStage
from etsy_listings.core.engine.stages.render import RenderStage

STAGES: list[AnyStage] = [
    RenderStage(),
    PrintifyProductStage(),
    PublishStage(),
    EtsyListingStage(),
    EtsyMediaStage(),
    EtsyVideosStage(),
]


def publishing_pipeline(stages: Sequence[AnyStage] = STAGES, *, publish: bool) -> list[AnyStage]:
    pipeline = list(stages)
    if publish:
        pipeline.append(EtsyActivateStage())
    return pipeline


__all__ = [
    "STAGES",
    "EtsyActivateStage",
    "EtsyListingStage",
    "EtsyMediaStage",
    "EtsyVideosStage",
    "PrintifyProductStage",
    "PublishStage",
    "RenderStage",
    "publishing_pipeline",
]

"""Concrete stages, in pipeline order (A1: order encodes dependency).

``Render()`` is the first real stage (Phase 1). Later phases add ``Generate``,
``PrintifyProduct``, ``Publish``, ``EtsyCopy`` and ``EtsyMedia`` after it.
"""

from __future__ import annotations

from etsy_listings.engine.stage import AnyStage
from etsy_listings.engine.stages.render import RenderStage

STAGES: list[AnyStage] = [RenderStage()]

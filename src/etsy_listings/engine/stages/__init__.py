"""Concrete stages, in pipeline order (A1: order encodes dependency, not a
dependency graph).

``Render()`` is the first real stage (Phase 1). Later phases add ``Generate``,
``PrintifyProduct``, ``Publish``, ``EtsyCopy`` and ``EtsyMedia`` after it --
which changes this list, and nothing in ``engine`` around it.

:data:`STAGES` is the interface. A stage's own types (``RenderDesired`` and
friends) are its business; the engine only ever sees them through the
:class:`~etsy_listings.engine.stage.Stage` protocol, with their types erased.
"""

from __future__ import annotations

from etsy_listings.engine.stage import AnyStage
from etsy_listings.engine.stages.render import RenderStage

STAGES: list[AnyStage] = [RenderStage()]

__all__ = ["STAGES", "RenderStage"]

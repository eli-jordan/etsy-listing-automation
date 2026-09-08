"""Concrete stages, in pipeline order (A1: order encodes dependency, not a
dependency graph).

``Render()`` came first (Phase 1); ``PrintifyProduct()`` follows it in Phase 2.
Later phases add ``Generate``, ``Publish``, ``EtsyCopy`` and ``EtsyMedia`` --
which changes this list, and nothing in ``engine`` around it.

**A stage in this list is not a stage that always runs.**
``PrintifyProduct`` reports itself unconfigured, rather than failing, in a
workspace with no ``printify.shop_id``: a listing whose copy is still
``<generate>`` is perfectly valid for rendering mockups, and a `plan` that
refused to run at all there would be a regression dressed as a validation.
Running ``setup`` is what opts a workspace in.

:data:`STAGES` is the interface. A stage's own types (``RenderDesired`` and
friends) are its business; the engine only ever sees them through the
:class:`~etsy_listings.engine.stage.Stage` protocol, with their types erased.
"""

from __future__ import annotations

from etsy_listings.engine.stage import AnyStage
from etsy_listings.engine.stages.printify_product import PrintifyProductStage
from etsy_listings.engine.stages.render import RenderStage

STAGES: list[AnyStage] = [RenderStage(), PrintifyProductStage()]

__all__ = ["STAGES", "PrintifyProductStage", "RenderStage"]

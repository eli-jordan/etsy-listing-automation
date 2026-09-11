"""Concrete stages, in pipeline order (A1: order encodes dependency, not a
dependency graph).

``Render()`` and ``PrintifyProduct()`` are Phase 1/2. Phase 3 adds
``Publish()``, ``EtsyListing()`` and ``EtsyMedia()`` -- in that order,
because each depends on what the one before it just did *this run*, via
A26's threading of ``lock.remote`` rather than a second lockfile read:
``Publish`` mints the Etsy listing id ``EtsyListing`` and ``EtsyMedia`` both
PATCH, and ``EtsyMedia`` needs whatever images survive the first two to
exist. ``Generate`` (Phase 4) is the one stage still to come.

**A stage in this list is not a stage that always runs.**
``PrintifyProduct`` reports itself unconfigured, rather than failing, in a
workspace with no ``printify.shop_id``: a listing whose copy is still
``<generate>`` is perfectly valid for rendering mockups, and a `plan` that
refused to run at all there would be a regression dressed as a validation.
Running ``setup`` is what opts a workspace in. ``Publish``/``EtsyListing``/
``EtsyMedia`` follow the same rule for ``etsy.shop_id``.

:data:`STAGES` is the interface. A stage's own types (``RenderDesired`` and
friends) are its business; the engine only ever sees them through the
:class:`~etsy_listings.engine.stage.Stage` protocol, with their types erased.
"""

from __future__ import annotations

from etsy_listings.engine.stage import AnyStage
from etsy_listings.engine.stages.etsy_listing import EtsyListingStage
from etsy_listings.engine.stages.etsy_media import EtsyMediaStage
from etsy_listings.engine.stages.printify_product import PrintifyProductStage
from etsy_listings.engine.stages.publish import PublishStage
from etsy_listings.engine.stages.render import RenderStage

STAGES: list[AnyStage] = [
    RenderStage(),
    PrintifyProductStage(),
    PublishStage(),
    EtsyListingStage(),
    EtsyMediaStage(),
]

__all__ = [
    "STAGES",
    "EtsyListingStage",
    "EtsyMediaStage",
    "PrintifyProductStage",
    "PublishStage",
    "RenderStage",
]

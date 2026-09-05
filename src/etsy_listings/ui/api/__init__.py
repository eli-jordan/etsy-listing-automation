"""The calibrator's HTTP surface: the app factory and its two routers.

Every path here comes from ``Workspace``. That is deliberate rather than
stylistic: template names, colours and design ids arrive from URLs, so routing
them through the workspace's accessors means the "stays inside the root" rule
(A8) is enforced by the same code the rest of the tool uses, instead of a
second, bespoke check living in the web layer.

Request and response shapes live in ``schemas``, except where ``template.yaml``
*is* the payload -- template CRUD reuses ``render.config``'s models directly,
since there is no wire-schema divergence to keep separate.
"""

from etsy_listings.ui.api.app import create_app
from etsy_listings.ui.api.designs import router as designs_router
from etsy_listings.ui.api.templates import router as templates_router

__all__ = ["create_app", "designs_router", "templates_router"]

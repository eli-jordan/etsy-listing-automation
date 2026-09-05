"""The calibrator: a FastAPI app and the React front end it serves.

Phase 1 carries only template calibration, because templates must be
calibrated before rendering is useful at all. The dashboard, setup wizard and
run runner land in Phase 5.

It is deliberately **not** a second execution path. The preview endpoint runs
the same renderer ``apply`` runs, over the same photo and derived maps that
``Workspace.scene_photo`` gives the render stage -- so the preview is the
actual output rather than an approximation of it. ``template.yaml`` is the
only thing that passes between the calibrator and the engine.

:func:`create_app` is the interface; ``etsy-listings ui`` hands it a
:class:`~etsy_listings.workspace.Workspace` and serves it with uvicorn.
"""

from etsy_listings.ui.api.app import create_app

__all__ = ["create_app"]

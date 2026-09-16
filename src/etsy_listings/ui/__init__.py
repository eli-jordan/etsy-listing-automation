"""The calibrator: a FastAPI app and the React front end it serves.

Phase 1 carries only template calibration, because templates must be
calibrated before rendering is useful at all. The dashboard, setup wizard and
run runner land in Phase 5.

It is deliberately **not** a second execution path. The preview endpoint runs
the same renderer ``apply`` runs, over the same photo and derived maps that
``Workspace.scene_photo`` gives the render stage -- so the preview is the
actual output rather than an approximation of it. ``template.yaml`` is the
only thing that passes between the calibrator and the engine.

It serves that output at two *sizes*, which is a different thing from serving
two renderers. The editing canvas asks for a downscale (``?scale=editor``) so
that dragging a box is live; the Preview tab asks for the photo's own size,
which is byte-for-byte the shape ``apply`` writes. Both go through
``render_scene``. What makes the fast one affordable is
:mod:`etsy_listings.ui.api.imagecache`, which memoises the decoded photo, the
decoded design and the derived maps across the burst of requests one drag
produces.

:func:`create_app` is the HTTP interface; :func:`run_calibrator` is what
``etsy-listings ui`` calls. By default that opens a native pywebview window
onto the same app uvicorn would serve; ``--browser`` is uvicorn in the
foreground, as before.
"""

from etsy_listings.ui.api.app import create_app
from etsy_listings.ui.desktop import run_calibrator

__all__ = ["create_app", "run_calibrator"]

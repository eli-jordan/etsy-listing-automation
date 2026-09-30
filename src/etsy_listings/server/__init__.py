"""The dashboard, listings and template editors, calibrator and run runner.

FastAPI serves the React SPA and the workspace-scoped HTTP API. Background
workers coordinate deployment runs and batch AI drafting.

It is deliberately **not** a second execution path. The preview endpoint runs
the same renderer ``apply`` runs, over the same photo and derived maps that
``Workspace.scene_photo`` gives the render stage -- so the preview is the
actual output rather than an approximation of it. Calibration persists
``template.yaml``. Listing plan previews also produce
content-addressed files that the engine can promote during apply (ADR-0040).

It serves that output at two *sizes*, which is a different thing from serving
two renderers. The editing canvas asks for a downscale (``?scale=editor``) so
that dragging a box is live; the Preview tab asks for the photo's own size,
which is byte-for-byte the shape ``apply`` writes. Both go through
``render_scene``. What makes the fast one affordable is
:mod:`etsy_listings.ui.api.imagecache`, which memoises the decoded photo, the
decoded design and the derived maps across the burst of requests one drag
produces.

:func:`create_app` is the HTTP interface; :func:`serve` is what
``etsy-listings ui`` calls to run it under uvicorn in the foreground.
"""

from etsy_listings.ui.api.app import create_app
from etsy_listings.ui.hosting import serve

__all__ = ["create_app", "serve"]

"""The HTTP server: the dashboard, listings and template editors, calibrator
and run runner (ADR-0052).

FastAPI serves the React SPA and the workspace-scoped HTTP API. Server owns
routing, wire schemas, HTTP status mapping, SSE framing, HTTP-oriented caches,
static serving and app startup/shutdown. Deployment runs, AI runs, the
batch AI queue and the write locks are core's (``core/application``); the
server constructs one of each per process and starts and stops them with
the app (module-structure plan, PR 8 and PR 9).

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
:mod:`etsy_listings.server.api.imagecache`, which memoises the decoded photo, the
decoded design and the derived maps across the burst of requests one drag
produces.

Two interfaces, deliberately not re-exported here so each has one import
path: :func:`etsy_listings.server.api.app.create_app` is the HTTP
application, and :func:`etsy_listings.server.hosting.serve` is the startup
interface -- the only server module the CLI may import, from its ``ui``
launcher (enforced by Import Linter in ``pyproject.toml``).
"""

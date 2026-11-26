"""The HTTP server: the dashboard, listings and template editors, calibrator
and run runner (ADR-0052).

FastAPI serves the React SPA and the workspace-scoped HTTP API. Server owns
routing, wire schemas, HTTP status mapping, SSE framing, HTTP-oriented caches,
static serving and app startup/shutdown. Deployment runs, AI runs, the batch
AI queue and the write locks are core's (``core/application``); the server
constructs one of each per process and starts and stops them with the app.

It is not a second execution path: previews run the same ``render_scene``
``apply`` runs, at the photo's own size or downscaled for the editing canvas
(``?scale=editor``, memoised by :mod:`etsy_listings.server.api.imagecache`).

Two interfaces, deliberately not re-exported here so each has one import
path: :func:`etsy_listings.server.api.app.create_app` is the HTTP
application, and :func:`etsy_listings.server.hosting.serve` is the startup
interface -- the only server module the CLI may import, from its ``ui``
launcher (enforced by Import Linter in ``pyproject.toml``).
"""

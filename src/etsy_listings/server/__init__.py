"""The HTTP server: FastAPI serving the React SPA and the workspace-scoped API over
the same core operations the CLI runs.

Not re-exported, so each has one import path:
:func:`etsy_listings.server.api.app.create_app` and
:func:`etsy_listings.server.hosting.serve`."""

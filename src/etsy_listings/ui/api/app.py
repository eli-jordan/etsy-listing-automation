"""FastAPI app factory. Phase 1 carried only the calibrator's endpoints (PRD:
"the calibration UI lands in phase 1 ... because templates must be calibrated
before rendering is useful at all"); phase 5 adds the listings list and editor
(``listings.py``); A33 adds the runs resource (``runs.py``) and the executor
thread behind it.

**Contexts are injected.** ``context_factory`` defaults to
``connections.run_context`` -- the assembly every real server uses -- but the
runs executor never calls ``connections`` directly (`connections.py`'s own
rule: "a credential is resolved when it is used, never when a client is
built"). A test passes a factory wired to in-memory fakes instead, and the
executor is none the wiser.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from etsy_listings import connections
from etsy_listings.ui.api.designs import router as designs_router
from etsy_listings.ui.api.listings import router as listings_router
from etsy_listings.ui.api.listings import support_router as listings_support_router
from etsy_listings.ui.api.media_files import router as media_files_router
from etsy_listings.ui.api.runs import router as runs_router
from etsy_listings.ui.api.seo import ActiveSeoRequests, AiProviderFactory, default_ai_providers
from etsy_listings.ui.api.seo import brief_router as ai_brief_router
from etsy_listings.ui.api.seo import router as seo_router
from etsy_listings.ui.api.templates import router as templates_router
from etsy_listings.ui.runs.executor import ContextFactory, RunExecutor
from etsy_listings.ui.runs.registry import RunRegistry
from etsy_listings.workspace.workspace import InvalidNameError, Workspace

FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"


def create_app(
    workspace: Workspace,
    *,
    context_factory: ContextFactory = connections.run_context,
    seo_provider_factory: AiProviderFactory = default_ai_providers,
) -> FastAPI:
    registry = RunRegistry()
    executor = RunExecutor(workspace=workspace, context_factory=context_factory, registry=registry)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Starts the runs executor's worker thread with the app, and waits
        for it on the way out -- the same "finish what's in flight, start
        nothing else" shutdown ``ui/desktop.py``'s close handler also needs
        (decision 7), except this is the path every ASGI server already calls
        (uvicorn's own shutdown, and ``TestClient``'s ``with`` block)."""
        executor.start()
        try:
            yield
        finally:
            executor.stop()

    app = FastAPI(title="etsy-listings", version="0.1.0", lifespan=lifespan)
    app.state.workspace = workspace
    app.state.run_registry = registry
    app.state.run_executor = executor
    # Shared with the preview endpoint (`listings.py`), which needs a
    # `RunContext` to ask the render stage for a scene's current hash but has
    # nothing to do with running a run -- reaching through `run_executor` for
    # it would couple that endpoint to the executor's own shape for no reason.
    app.state.context_factory = context_factory
    # `ui/api/seo.py`'s own injection seam and its in-memory
    # one-request-per-listing tracker -- deliberately not part of
    # `run_registry`/`run_executor` above, since a proposal request is never
    # a `Run` (PR5 item 5: no run, no SQLite record, no server-side cache).
    app.state.seo_provider_factory = seo_provider_factory
    app.state.seo_active_requests = ActiveSeoRequests()

    # Permissive CORS for local dev only -- the Vite dev server proxies /api in
    # production-shaped use, but running `uvicorn` and `vite` as two separate
    # processes during development needs this.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(InvalidNameError)
    async def invalid_name(request: Request, exc: Exception) -> Response:
        """A template, colour or design id from a URL that is not a single
        path segment is the client's fault, so it is a 400 -- and it is one
        rule, so it is stated once here.

        Nine endpoints used to wrap their own ``workspace.…(name)`` call in
        the same three lines to say so. The refusal itself still belongs to
        ``Workspace`` (A8 makes it a security boundary, not a formatting
        concern); all this does is decide the status code it surfaces as.
        """
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    app.include_router(templates_router)
    app.include_router(designs_router)
    app.include_router(listings_router)
    app.include_router(listings_support_router)
    app.include_router(media_files_router)
    app.include_router(runs_router)
    app.include_router(seo_router)
    app.include_router(ai_brief_router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "workspace": str(workspace.root)}

    if FRONTEND_DIST.is_dir():
        # Built assets under /assets; everything else falls back to
        # index.html so client-side routing works on a hard refresh.
        # `npm run build` (A5) must have run first -- in dev, use the Vite
        # dev server instead and hit uvicorn only for /api.
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        @app.get("/{full_path:path}")
        def spa_fallback(full_path: str, request: Request) -> Response:
            if full_path.startswith("api/"):
                return JSONResponse(status_code=404, content={"detail": "not found"})
            return FileResponse(FRONTEND_DIST / "index.html")

    return app

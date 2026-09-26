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
from etsy_listings.clients.etsy.market import EtsyMarketClient
from etsy_listings.ui.airuns.registry import AiRunRegistry
from etsy_listings.ui.airuns.runner import AiRunner, MarketClientFactory
from etsy_listings.ui.api.airuns import router as ai_runs_router
from etsy_listings.ui.api.designs import router as designs_router
from etsy_listings.ui.api.listings import router as listings_router
from etsy_listings.ui.api.listings import support_router as listings_support_router
from etsy_listings.ui.api.media_files import router as media_files_router
from etsy_listings.ui.api.runs import router as runs_router
from etsy_listings.ui.api.seo import AiProviderFactory, default_ai_providers
from etsy_listings.ui.api.seo import router as seo_router
from etsy_listings.ui.api.templates import router as templates_router
from etsy_listings.ui.runs.executor import ContextFactory, RunExecutor
from etsy_listings.ui.runs.registry import RunRegistry
from etsy_listings.ui.workspace_locks import WorkspaceLocks
from etsy_listings.workspace.workspace import InvalidNameError, Workspace

FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"


def default_market_client(workspace: Workspace) -> EtsyMarketClient | None:
    """The real, read-only Etsy market client (the app key only), or `None`
    when the workspace has none."""
    return connections.etsy_market_client(workspace.root)


def create_app(
    workspace: Workspace,
    *,
    context_factory: ContextFactory = connections.run_context,
    seo_provider_factory: AiProviderFactory = default_ai_providers,
    market_client_factory: MarketClientFactory = default_market_client,
) -> FastAPI:
    registry = RunRegistry()
    executor = RunExecutor(workspace=workspace, context_factory=context_factory, registry=registry)
    locks = WorkspaceLocks()
    ai_registry = AiRunRegistry()
    ai_runner = AiRunner(
        workspace=workspace,
        registry=ai_registry,
        locks=locks,
        providers=seo_provider_factory,
        market_client=market_client_factory,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Starts the runs executor's worker thread with the app, and waits
        for it on the way out -- the same "finish what's in flight, start
        nothing else" shutdown ``ui/desktop.py``'s close handler also needs
        (decision 7), except this is the path every ASGI server already calls
        (uvicorn's own shutdown, and ``TestClient``'s ``with`` block).

        AI runs are cancelled first: each is on its own daemon thread, and
        cancelling kills its provider subprocess tree, so a server stopping
        never waits out a model."""
        executor.start()
        try:
            yield
        finally:
            ai_runner.shutdown()
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
    # The AI providers' injection seam, read per request by AI Mode's
    # readiness check (`seo.py`) and per run by `ai_runner`.
    app.state.seo_provider_factory = seo_provider_factory
    # Held around every read-merge-write of a listing (`listings.py`, and
    # PR 5's brief write) -- `ui/workspace_locks.py` says why.
    app.state.workspace_locks = locks
    # AI runs (market-seo.md, *AI runs*): their own registry and a thread per
    # run, never `run_executor`. `market_client_factory` is the test seam for
    # Etsy market search, as `seo_provider_factory` is for the providers.
    app.state.ai_run_registry = ai_registry
    app.state.ai_runner = ai_runner

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
    app.include_router(ai_runs_router)
    app.include_router(seo_router)

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

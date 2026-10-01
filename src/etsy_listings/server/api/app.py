"""FastAPI app factory for the calibrator, listings, AI runs and batch workflows.

The routes share one workspace and the same engine services as the CLI.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from etsy_listings.core import connections
from etsy_listings.core.ai.proposals import ProposalStore
from etsy_listings.core.application.ai.batch_queue import BatchQueue
from etsy_listings.core.application.ai.registry import AiRunRegistry
from etsy_listings.core.application.ai.runner import AiRunner, MarketClientFactory
from etsy_listings.core.application.deploy.deployments import Deployments
from etsy_listings.core.application.deploy.executor import ContextFactory
from etsy_listings.core.application.workspace_locks import WorkspaceLocks
from etsy_listings.core.batches import BatchStore, StagingStore
from etsy_listings.core.clients.etsy.market import EtsyMarketClient
from etsy_listings.core.workspace.workspace import InvalidNameError, Workspace
from etsy_listings.server.api.airuns import router as ai_runs_router
from etsy_listings.server.api.batches import router as batches_router
from etsy_listings.server.api.designs import router as designs_router
from etsy_listings.server.api.listing_templates import router as listing_templates_router
from etsy_listings.server.api.listings import router as listings_router
from etsy_listings.server.api.listings import support_router as listings_support_router
from etsy_listings.server.api.media_files import router as media_files_router
from etsy_listings.server.api.runs import router as runs_router
from etsy_listings.server.api.seo import AiProviderFactory, default_ai_providers
from etsy_listings.server.api.seo import router as seo_router
from etsy_listings.server.api.templates import router as templates_router


def _frontend_dist() -> Path:
    """The built SPA: an installed wheel carries it in `etsy_listings/server/static`
    (pyproject.toml's `assets-dir`, mapped by hatch_build.py); an editable
    checkout has none there and serves `src/ui/dist`, wherever npm last built it."""
    packaged = Path(__file__).parent.parent / "static"
    return packaged if packaged.is_dir() else Path(__file__).parents[3] / "ui" / "dist"


FRONTEND_DIST = _frontend_dist()


def default_market_client(workspace: Workspace) -> EtsyMarketClient | None:
    """The real, read-only Etsy market client (the app key only), or `None`
    when the workspace has none."""
    if connections.etsy_app_key(workspace.root) is None:
        return None
    return connections.etsy_market_client(workspace.root)


def create_app(
    workspace: Workspace,
    *,
    context_factory: ContextFactory = connections.run_context,
    seo_provider_factory: AiProviderFactory = default_ai_providers,
    market_client_factory: MarketClientFactory = default_market_client,
) -> FastAPI:
    locks = WorkspaceLocks()
    ai_registry = AiRunRegistry()
    proposal_store = ProposalStore(workspace)
    ai_runner = AiRunner(
        workspace=workspace,
        registry=ai_registry,
        locks=locks,
        providers=seo_provider_factory,
        market_client=market_client_factory,
        proposals=proposal_store,
    )
    staging_store = StagingStore(workspace)
    batch_store = BatchStore(workspace)
    batch_queue = BatchQueue(
        workspace=workspace, batches=batch_store, registry=ai_registry, runner=ai_runner
    )
    # Constructing it starts nothing; the lifespan below does. Deploying
    # takes precedence over AI work through the batch queue (ADR-0050).
    deployments = Deployments(
        workspace, context_factory, yield_to_deploy=batch_queue.yield_to_deploy
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Starts the deployment worker thread with the app, and waits
        for it on the way out -- "finish what's in flight, start nothing
        else" (decision 7), on the path every ASGI server already calls
        (uvicorn's own shutdown when ``ui`` is interrupted, and
        ``TestClient``'s ``with`` block).

        AI runs are cancelled first: each is on its own daemon thread, and
        cancelling kills its provider subprocess tree, so a server stopping
        never waits out a model.

        Expired staging sessions are swept on the way in. The batch
        queue starts with the app, returning rows a previous server left
        running to the queue, and stops before the AI runs are cancelled, so
        it starts nothing into a runner that is shutting down."""
        staging_store.sweep(now=datetime.now(UTC))
        deployments.start()
        batch_queue.start()
        try:
            yield
        finally:
            batch_queue.stop()
            ai_runner.shutdown()
            deployments.stop()

    app = FastAPI(title="etsy-listings", version="0.1.0", lifespan=lifespan)
    app.state.workspace = workspace
    app.state.deployments = deployments
    # Shared with the preview endpoint (`listings.py`), which needs a
    # `RunContext` to ask the render stage for a scene's current hash but has
    # nothing to do with running a run -- reaching through `deployments` for
    # it would couple that endpoint to deployment's own shape for no reason.
    app.state.context_factory = context_factory
    # The AI providers' injection seam, read per request by AI Mode's
    # readiness check (`seo.py`) and per run by `ai_runner`.
    app.state.seo_provider_factory = seo_provider_factory
    # Held around every read-merge-write of a listing (`listings.py`, and
    # PR 5's brief write) -- `core/application/workspace_locks.py` says why.
    app.state.workspace_locks = locks
    # AI runs (features/market-seo-20260924/spec.md, *AI runs*): their own registry and a thread per
    # run, never `deployments`. `market_client_factory` is the test seam for
    # Etsy market search, as `seo_provider_factory` is for the providers.
    app.state.ai_run_registry = ai_registry
    app.state.ai_runner = ai_runner
    # Batch creation's cache records: one store of each per process, so
    # their per-record locks mean something.
    app.state.staging_store = staging_store
    app.state.batch_store = batch_store
    # ADR-0048: the batch AI queue, dispatching batch rows onto `ai_runner`.
    # `market_client_factory` is also what staging's AI readiness asks.
    app.state.batch_queue = batch_queue
    app.state.market_client_factory = market_client_factory
    # ADR-0049: the cached proposals, written by `ai_runner` and read and resolved
    # through `seo.py`. One store, for the same reason.
    app.state.proposal_store = proposal_store

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
        ``Workspace`` (ADR-0013 makes it a security boundary, not a formatting
        concern); all this does is decide the status code it surfaces as.
        """
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    app.include_router(templates_router)
    app.include_router(designs_router)
    app.include_router(listings_router)
    app.include_router(listings_support_router)
    app.include_router(listing_templates_router)
    app.include_router(batches_router)
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
        # `npm run build` must have run first -- in dev, use the Vite
        # dev server instead and hit uvicorn only for /api.
        app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

        # Out of the schema: it is not API, and the exported contract must
        # not depend on whether this checkout has a built SPA.
        @app.get("/{full_path:path}", include_in_schema=False)
        def spa_fallback(full_path: str, request: Request) -> Response:
            if full_path.startswith("api/"):
                return JSONResponse(status_code=404, content={"detail": "not found"})
            return FileResponse(FRONTEND_DIST / "index.html")

    return app

"""FastAPI app factory for the calibrator, listings, AI runs and batch workflows.

The routes share one workspace and the same engine services as the CLI.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from etsy_listings.core import connections
from etsy_listings.core.ai.discovery import ModelDiscovery
from etsy_listings.core.ai.proposals import ProposalStore
from etsy_listings.core.application.ai.coordinator import AiCoordinator
from etsy_listings.core.application.ai.readiness import ProviderFactory, default_ai_providers
from etsy_listings.core.application.dependencies import (
    DEFAULT_CLIENTS,
    ClientFactories,
    ContextFactory,
)
from etsy_listings.core.application.deploy.deployments import Deployments
from etsy_listings.core.application.preparation.coordinator import Preparations
from etsy_listings.core.application.preparation.dependencies import PreparationRuntime
from etsy_listings.core.application.scene_warming import SceneWarmer
from etsy_listings.core.batches import BatchStore, StagingStore
from etsy_listings.core.errors import ConflictError, MissingError, RefusedError, StaleError
from etsy_listings.core.workspace.workspace import InvalidNameError, Workspace
from etsy_listings.server.api.airuns import router as ai_runs_router
from etsy_listings.server.api.batches import router as batches_router
from etsy_listings.server.api.designs import router as designs_router
from etsy_listings.server.api.listing_templates import router as listing_templates_router
from etsy_listings.server.api.listings import router as listings_router
from etsy_listings.server.api.listings import support_router as listings_support_router
from etsy_listings.server.api.media_files import router as media_files_router
from etsy_listings.server.api.preparation import router as preparation_router
from etsy_listings.server.api.runs import router as runs_router
from etsy_listings.server.api.seo import router as seo_router
from etsy_listings.server.api.shop import router as shop_router
from etsy_listings.server.api.templates import router as templates_router
from etsy_listings.server.api.workspace_settings import router as workspace_settings_router


def _frontend_dist() -> Path:
    """The built SPA: an installed wheel carries it in `etsy_listings/server/static`
    (pyproject.toml's `assets-dir`, mapped by hatch_build.py); an editable
    checkout has none there and serves `src/ui/dist`, wherever npm last built it."""
    packaged = Path(__file__).parent.parent / "static"
    return packaged if packaged.is_dir() else Path(__file__).parents[3] / "ui" / "dist"


FRONTEND_DIST = _frontend_dist()


def create_app(
    workspace: Workspace,
    *,
    context_factory: ContextFactory = connections.run_context,
    seo_provider_factory: ProviderFactory = default_ai_providers,
    preparation_runtime: PreparationRuntime | None = None,
    clients: ClientFactories = DEFAULT_CLIENTS,
) -> FastAPI:
    # One of each per process, so their locks mean something: the cache
    # records' stores. Listing, mockup-template and listing-template locks need
    # no instance; `core/workspace/locks.py` keys them by workspace root.
    preparations = Preparations(workspace, runtime=preparation_runtime)
    proposal_store = ProposalStore(workspace)
    staging_store = StagingStore(workspace)
    batch_store = BatchStore(workspace)
    # Constructing the coordinators starts nothing; the lifespan below does.
    # Deploying takes precedence over AI work (ADR-0050).
    ai = AiCoordinator(
        workspace,
        proposals=proposal_store,
        batches=batch_store,
        providers=seo_provider_factory,
        market_client=clients.etsy_market,
    )
    deployments = Deployments(workspace, context_factory, ai=ai)
    scene_warmer = SceneWarmer(workspace)

    @asynccontextmanager
    async def lifespan(running: FastAPI) -> AsyncIterator[None]:
        """Starts the deployment worker thread with the app, and waits
        for it on the way out -- "finish what's in flight, start nothing
        else" (decision 7), on the path every ASGI server already calls
        (uvicorn's own shutdown when ``ui`` is interrupted, and
        ``TestClient``'s ``with`` block).

        AI work stops first: its batch queue starts nothing more, then every
        AI run is cancelled -- each on its own daemon thread, its provider
        subprocess tree killed -- so a server stopping never waits out a
        model, and a deploy yielding to a run is not left waiting on it.

        Expired staging sessions are swept on the way in. The batch queue
        starts with the app, returning rows a previous server left running
        to the queue.

        The scene warmer stops before the rest, abandoning its queue: what
        it composes is only ever a head start."""
        await run_in_threadpool(preparations.start)
        # ADR-0056: discovery is advisory. Its owned worker must not hold
        # application availability behind installed CLI processes.
        # Read from app.state, so a test can put its own discovery there first.
        discovery: ModelDiscovery = running.state.model_discovery
        discovery.start()
        staging_store.sweep(now=datetime.now(UTC))
        deployments.start()
        ai.start()
        scene_warmer.start()
        try:
            yield
        finally:
            await run_in_threadpool(discovery.stop)
            scene_warmer.stop()
            ai.stop()
            deployments.stop()
            await run_in_threadpool(preparations.close)

    app = FastAPI(title="etsy-listings", version="0.1.0", lifespan=lifespan)
    app.state.preparations = preparations
    app.state.workspace = workspace
    app.state.model_discovery = ModelDiscovery()
    app.state.deployments = deployments
    # Shared with the preview endpoint (`listings.py`), which needs a
    # `RunContext` to ask the render stage for a scene's current hash but has
    # nothing to do with running a run -- reaching through `deployments` for
    # it would couple that endpoint to deployment's own shape for no reason.
    app.state.context_factory = context_factory
    # The Etsy and Printify clients the routes ask through (`app_state.clients`),
    # injected for the same reason as the context factory: a test passes fakes.
    app.state.clients = clients
    # AI runs (features/market-seo-20260924/spec.md, *AI runs*) and the
    # batch AI queue (ADR-0048): a thread per run, never `deployments`.
    app.state.ai = ai
    app.state.staging_store = staging_store
    app.state.batch_store = batch_store
    # ADR-0049: the cached proposals, written by AI runs and read and resolved
    # through `seo.py`. One store, for the same reason.
    app.state.proposal_store = proposal_store
    # Composes a saved listing's gallery scenes ahead of the Listing Images
    # tab asking for them (`listings.py`'s create and PATCH).
    app.state.scene_warmer = scene_warmer

    # Permissive CORS for local dev only -- the Vite dev server proxies /api in
    # production-shaped use, but running `uvicorn` and `vite` as two separate
    # processes during development needs this.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_refusals(app)

    for router in API_ROUTERS:
        app.include_router(router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "workspace": str(workspace.root)}

    if FRONTEND_DIST.is_dir():
        _serve_frontend(app, FRONTEND_DIST)

    return app


API_ROUTERS = (
    preparation_router,
    templates_router,
    designs_router,
    listings_router,
    listings_support_router,
    listing_templates_router,
    batches_router,
    media_files_router,
    runs_router,
    ai_runs_router,
    seo_router,
    shop_router,
    workspace_settings_router,
)


REFUSAL_STATUS: Mapping[type[Exception], int] = {
    InvalidNameError: 400,
    MissingError: 404,
    ConflictError: 409,
    StaleError: 412,
    RefusedError: 422,
}
"""Each refusal category (``core/errors.py``) as the status it surfaces as.

The one place a core refusal becomes a status code, so a route only lets it
through. Core declares the category and never a code (ADR-0052); the routes
used to decide per router, and disagreed -- a missing test design was a 400
where every other missing thing was a 404, and a calibration conflict was a
409 or a 412 depending on what its message said.

* ``400``: a name from a URL or a body that the server will not take as a name
  -- not a single path segment (ADR-0013 makes that a security boundary, so
  the refusal belongs to ``Workspace``), or reserved.
* ``404``: what the request names is not there.
* ``409``: the request is fine, but what the workspace holds now forbids it.
* ``412``: the request was made against a revision that has since changed;
  reload and ask again.
* ``422``: the request's own content cannot be taken.

The detail is the refusal's message: a ``UserFacingError``'s message is the
whole of what should reach a reader. A route whose refusal carries more than a
sentence -- a staging refusal's remedy, an AI run's reason, the Admin page's
field errors -- still answers it itself, with the status this table gives its
category. Starlette picks a handler by walking the exception's MRO, so a class
answers as the first category among its bases."""


def register_refusals(app: FastAPI) -> None:
    """Answer every refusal category with its :data:`REFUSAL_STATUS`."""
    for category, status in REFUSAL_STATUS.items():
        app.add_exception_handler(category, _refusal_handler(status))


def _refusal_handler(status: int) -> Callable[[Request, Exception], Awaitable[Response]]:
    async def answer(_request: Request, exc: Exception) -> Response:
        return JSONResponse(status_code=status, content={"detail": str(exc)})

    return answer


def _serve_frontend(app: FastAPI, dist: Path) -> None:
    """Built assets under /assets; everything else falls back to
    index.html so client-side routing works on a hard refresh.
    `npm run build` must have run first -- in dev, use the Vite
    dev server instead and hit uvicorn only for /api."""
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    # Out of the schema: it is not API, and the exported contract must
    # not depend on whether this checkout has a built SPA.
    @app.get("/{full_path:path}", include_in_schema=False)
    def spa_fallback(full_path: str) -> Response:
        if full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "not found"})
        return FileResponse(dist / "index.html")

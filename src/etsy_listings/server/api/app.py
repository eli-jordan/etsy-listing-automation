from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from etsy_listings.core import connections
from etsy_listings.core.ai.discovery import ModelDiscovery
from etsy_listings.core.ai.proposals import ProposalStore
from etsy_listings.core.application.ai.coordinator import AiCoordinator
from etsy_listings.core.application.ai.readiness import ProviderFactory, default_ai_providers
from etsy_listings.core.application.backup_coordinator import BackupCoordinator, BackupEnvironment
from etsy_listings.core.application.dependencies import (
    DEFAULT_CLIENTS,
    ClientFactories,
    ContextFactory,
)
from etsy_listings.core.application.deploy.deployments import Deployments
from etsy_listings.core.application.job_gate import JobGate
from etsy_listings.core.application.preparation.coordinator import Preparations
from etsy_listings.core.application.preparation.dependencies import PreparationRuntime
from etsy_listings.core.application.scene_warming import SceneWarmer
from etsy_listings.core.batches import BatchStore, StagingStore
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.airuns import router as ai_runs_router
from etsy_listings.server.api.backup import router as backup_router
from etsy_listings.server.api.batches import router as batches_router
from etsy_listings.server.api.designs import router as designs_router
from etsy_listings.server.api.listing_templates import router as listing_templates_router
from etsy_listings.server.api.listings import router as listings_router
from etsy_listings.server.api.listings import support_router as listings_support_router
from etsy_listings.server.api.media_files import router as media_files_router
from etsy_listings.server.api.preparation import router as preparation_router
from etsy_listings.server.api.refusal_status import REFUSAL_STATUS
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


def create_app(  # noqa: PLR0913 -- every argument after the workspace is a test seam with a default
    workspace: Workspace,
    *,
    context_factory: ContextFactory = connections.run_context,
    seo_provider_factory: ProviderFactory = default_ai_providers,
    preparation_runtime: PreparationRuntime | None = None,
    clients: ClientFactories = DEFAULT_CLIENTS,
    backup: BackupEnvironment | None = None,
    model_discovery: ModelDiscovery | None = None,
) -> FastAPI:
    # One of each per process, so their locks mean something: the cache
    # records' stores. Listing, mockup-template and listing-template locks need
    # no instance; `core/workspace/locks.py` keys them by workspace root.
    job_gate = JobGate()
    preparations = Preparations(workspace, runtime=preparation_runtime, gate=job_gate)
    proposal_store = ProposalStore(workspace)
    staging_store = StagingStore(workspace)
    batch_store = BatchStore(workspace)
    ai = AiCoordinator(
        workspace,
        proposals=proposal_store,
        batches=batch_store,
        providers=seo_provider_factory,
        market_client=clients.etsy_market,
        gate=job_gate,
    )
    deployments = Deployments(workspace, context_factory, ai=ai, gate=job_gate)
    scene_warmer = SceneWarmer(workspace, gate=job_gate)
    backups = BackupCoordinator(workspace, gate=job_gate, environment=backup)
    discovery = ModelDiscovery() if model_discovery is None else model_discovery

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        await run_in_threadpool(preparations.start)
        discovery.start()
        staging_store.sweep(now=datetime.now(UTC))
        deployments.start()
        ai.start()
        scene_warmer.start()
        backups.start()
        try:
            yield
        finally:
            job_gate.stop()
            await run_in_threadpool(backups.stop)
            await run_in_threadpool(discovery.stop)
            scene_warmer.stop()
            ai.stop()
            deployments.stop()
            await run_in_threadpool(preparations.close)

    app = FastAPI(title="etsy-listings", version="0.1.0", lifespan=lifespan)
    app.state.preparations = preparations
    app.state.workspace = workspace
    app.state.model_discovery = discovery
    app.state.deployments = deployments
    app.state.job_gate = job_gate
    app.state.backups = backups
    app.state.context_factory = context_factory
    app.state.clients = clients
    app.state.ai = ai
    app.state.staging_store = staging_store
    app.state.batch_store = batch_store
    app.state.proposal_store = proposal_store
    app.state.scene_warmer = scene_warmer

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
    backup_router,
)


def register_refusals(app: FastAPI) -> None:
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

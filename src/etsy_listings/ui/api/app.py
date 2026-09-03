"""FastAPI app factory. Phase 1 carries only the calibrator's endpoints
(PRD: "the calibration UI lands in phase 1 ... because templates must be
calibrated before rendering is useful at all"); the dashboard, setup wizard
and run endpoints in the plan's ``## UI`` section land in Phase 5.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from etsy_listings.ui.api.templates import router as templates_router
from etsy_listings.workspace.workspace import Workspace

FRONTEND_DIST = Path(__file__).parent.parent / "frontend" / "dist"


def create_app(workspace: Workspace) -> FastAPI:
    app = FastAPI(title="etsy-listings", version="0.1.0")
    app.state.workspace = workspace

    # Permissive CORS for local dev only -- the Vite dev server proxies /api in
    # production-shaped use, but running `uvicorn` and `vite` as two separate
    # processes during development needs this.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(templates_router)

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

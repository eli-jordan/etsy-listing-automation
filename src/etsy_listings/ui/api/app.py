"""FastAPI app factory. Phase 1 carries only the calibrator's endpoints
(PRD: "the calibration UI lands in phase 1 ... because templates must be
calibrated before rendering is useful at all"); the dashboard, setup wizard
and run endpoints in the plan's ``## UI`` section land in Phase 5.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from etsy_listings.ui.api.templates import router as templates_router
from etsy_listings.workspace.workspace import Workspace


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

    return app

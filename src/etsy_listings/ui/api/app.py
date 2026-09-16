"""FastAPI app factory. Phase 1 carried only the calibrator's endpoints (PRD:
"the calibration UI lands in phase 1 ... because templates must be calibrated
before rendering is useful at all"); phase 5 adds the listings list and editor
(``listings.py``). The dashboard's real content and a Runner/plan-apply
trigger are still not here -- see ``docs/phase-5-listings-ui.md``.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from etsy_listings.ui.api.designs import router as designs_router
from etsy_listings.ui.api.listings import router as listings_router
from etsy_listings.ui.api.listings import support_router as listings_support_router
from etsy_listings.ui.api.templates import router as templates_router
from etsy_listings.workspace.workspace import InvalidNameError, Workspace

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

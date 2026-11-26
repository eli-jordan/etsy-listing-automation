"""Exports the FastAPI app's OpenAPI schema to docs/openapi.json, which
``npm run gen:api`` then turns into the frontend's typed client (ADR-0011: "TS
client generated from the OpenAPI schema -- never hand-written").

Run with ``uv run python scripts/export_openapi.py`` whenever an endpoint's
shape changes, then ``npm run gen:api`` in src/ui/. ``tests/test_export_openapi.py``
fails when the committed file is stale, and ``npm run check:api`` when schema.ts is.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from etsy_listings.core.config.defaults import Defaults, EtsyDefaults
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.app import create_app

REPO_ROOT = Path(__file__).parent.parent
CONTRACT = REPO_ROOT / "docs" / "openapi.json"


def build_schema() -> dict[str, Any]:
    """The app's OpenAPI document, as committed to docs/openapi.json."""
    # The schema only reflects route/model shapes, not runtime data, so a
    # placeholder workspace (never opened against real files) is enough.
    dummy_defaults = Defaults(etsy=EtsyDefaults(currency="NOK"))
    workspace = Workspace(root=REPO_ROOT, defaults=dummy_defaults)
    return create_app(workspace).openapi()


def render_schema() -> bytes:
    """docs/openapi.json's bytes, with CRLF endings on every OS so an export
    from Linux matches the committed file."""
    text = json.dumps(build_schema(), indent=2, sort_keys=True) + "\n"
    return text.replace("\n", "\r\n").encode("utf-8")


def main() -> None:
    CONTRACT.write_bytes(render_schema())
    print(f"wrote {CONTRACT}")


if __name__ == "__main__":
    main()

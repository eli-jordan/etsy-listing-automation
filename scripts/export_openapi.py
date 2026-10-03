"""Exports the FastAPI app's OpenAPI schema to docs/openapi.json, which
openapi-typescript then turns into the frontend's typed client (ADR-0011: "TS
client generated from the OpenAPI schema -- never hand-written").

Run with ``uv run python scripts/export_openapi.py`` whenever an endpoint's
shape changes, then ``npm run gen:api`` in src/ui/. CI checks frontend
types but does not currently regenerate this contract to detect a stale export.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from etsy_listings.core.config.defaults import Defaults, EtsyDefaults
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.app import create_app

REPO_ROOT = Path(__file__).parent.parent


def build_schema() -> dict[str, Any]:
    """The app's OpenAPI document, as committed to docs/openapi.json."""
    # The schema only reflects route/model shapes, not runtime data, so a
    # placeholder workspace (never opened against real files) is enough.
    dummy_defaults = Defaults(etsy=EtsyDefaults(currency="NOK"))
    workspace = Workspace(root=REPO_ROOT, defaults=dummy_defaults)
    return create_app(workspace).openapi()


def main() -> None:
    schema = build_schema()
    out_path = REPO_ROOT / "docs" / "openapi.json"
    out_path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()

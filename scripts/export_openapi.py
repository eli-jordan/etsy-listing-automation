"""Exports the FastAPI app's OpenAPI schema to docs/openapi.json, which
openapi-typescript then turns into the frontend's typed client (A5: "TS
client generated from the OpenAPI schema -- never hand-written").

Run with ``uv run python scripts/export_openapi.py`` whenever an endpoint's
shape changes, then ``npm run gen:api`` in ui/frontend/. CI should run both
and fail on a diff (A5 risk 3) -- not yet wired since there's no CI in this
repo yet.
"""

from __future__ import annotations

import json
from pathlib import Path

from etsy_listings.config.defaults import Defaults, EtsyDefaults
from etsy_listings.ui.api.app import create_app
from etsy_listings.workspace.workspace import Workspace

REPO_ROOT = Path(__file__).parent.parent


def main() -> None:
    # The schema only reflects route/model shapes, not runtime data, so a
    # placeholder workspace (never opened against real files) is enough.
    dummy_defaults = Defaults(
        etsy=EtsyDefaults(
            shop_id=0,
            who_made="i_did",
            when_made="made_to_order",
            is_supply=False,
            shop_section_id=0,
            return_policy_id=0,
        ),
        currency="NOK",
    )
    workspace = Workspace(root=REPO_ROOT, defaults=dummy_defaults)
    app = create_app(workspace)

    schema = app.openapi()
    out_path = REPO_ROOT / "docs" / "openapi.json"
    out_path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()

"""A batch-created listing, deployed against the real Printify and Etsy APIs
(batch plan PR 8; spec, *Deployment interaction*; A43, A44). ``-m e2e``,
skipped by default.

The Phase 3 test deploys the fixture listing; this one deploys a listing
nothing but the batch path made, through the app the seller drives: the
fixture listing saved as a listing template, one print-size design staged
and confirmed, the batch queue drafting its brief, market research and
proposal, the proposal's first title and lead accepted into the listing,
and then a UI plan and an apply through the runs resource. A listing
template carries no title or lead, so until the seller accepts them the
listing cannot deploy at all -- which is why accepting them is the step
between the batch and the deploy.

What it adds over the offline suite is that a listing the batch path wrote
is one the real pipeline accepts: every stage runs, nothing is blocked, and
the Etsy draft carries the accepted title. And that the UI apply's full
success removes the proposal (A44), against a real deploy.

**Costs state** exactly as the Phase 3 test does: one Printify product,
published as an Etsy draft, deleted in teardown (which removes the draft
too; see that module's docstring). AI is the conftest's fake by default
(``E2E_REAL_AI=1`` for the signed-in providers); market research is real,
so this needs the Etsy app key as well as the sign-in.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml
from fastapi.testclient import TestClient

from etsy_listings import connections
from etsy_listings.ai.brief import default_brief_prompt_text
from etsy_listings.ai.market_queries import default_market_queries_prompt_text
from etsy_listings.ai.prompt import default_seo_prompt_text
from etsy_listings.ai.providers import AiProvider
from etsy_listings.clients.etsy import HttpEtsyListingClient
from etsy_listings.clients.printify import HttpCatalogClient
from etsy_listings.clients.printify import Transport as PrintifyTransport
from etsy_listings.clients.printify.protocol import PrintifyClient
from etsy_listings.engine.context import EventSink, RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.stages.etsy_target import ETSY_LISTING_ID_KEY
from etsy_listings.engine.stages.printify_product import PRODUCT_ID_KEY
from etsy_listings.ui.api.app import create_app
from etsy_listings.workspace.workspace import Workspace

from tests.conftest import FIXTURE_WORKSPACE
from tests.e2e.conftest import PrerequisiteMissing, point_at_throwaway_shops
from tests.support.ai_runs import wait_for
from tests.support.batches import png
from tests.support.builders import FIXTURE_LISTING

pytestmark = pytest.mark.e2e

LISTING_TEMPLATE = "e2e-batch-tee"
DESIGN = "e2e-batch-trail"
"""The staged file's stem, and so the listing's name (A38)."""
PRINT_AREA = (4500, 5400)
"""The fixture garment profile's print area: a design any smaller is
blocked before the product stage creates anything (PRD 38)."""
AI_SECONDS = 240.0
"""The runner's own limit is 180 s; the rest is the queue's turn."""


@pytest.fixture
def workspace(
    tmp_path: Path,
    credentials_workspace: Workspace,
    etsy_client: HttpEtsyListingClient,
    prerequisite_missing: PrerequisiteMissing,
) -> Workspace:
    root = tmp_path / "workspace"
    shutil.copytree(FIXTURE_WORKSPACE, root)
    point_at_throwaway_shops(root, credentials_workspace, etsy_client, prerequisite_missing)
    workspace = Workspace.discover(root_override=root)
    for path, content in (
        (workspace.brief_prompt_file(), default_brief_prompt_text()),
        (workspace.market_queries_prompt_file(), default_market_queries_prompt_text()),
        (workspace.seo_prompt_file(), default_seo_prompt_text()),
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return workspace


@pytest.fixture
def client(
    workspace: Workspace,
    printify_token: str,
    printify_client: PrintifyClient,
    etsy_client: HttpEtsyListingClient,
    etsy_market_workspace: Workspace,
    ai_providers: Callable[[Workspace], Sequence[AiProvider]],
) -> Iterator[TestClient]:
    catalog = HttpCatalogClient(PrintifyTransport(printify_token))

    def real_context(ws: Workspace, on_event: EventSink | None) -> RunContext:
        sink = {"on_event": on_event} if on_event is not None else {}
        return RunContext(
            workspace=ws, catalog=catalog, printify=printify_client, etsy=etsy_client, **sink
        )

    app = create_app(
        workspace,
        context_factory=real_context,
        seo_provider_factory=ai_providers,
        market_client_factory=lambda _workspace: connections.etsy_market_client(
            etsy_market_workspace.root
        ),
    )
    with TestClient(app) as client:
        yield client


@pytest.fixture(autouse=True)
def cleanup_product(workspace: Workspace, printify_client: PrintifyClient) -> Iterator[None]:
    """Deletes the product the deploy created, which removes its Etsy draft."""
    try:
        yield
    finally:
        existing = Lockfile.read(workspace.lock_file(DESIGN))
        product_id = existing.remote.get(PRODUCT_ID_KEY) if existing is not None else None
        if product_id:
            shop_id = workspace.defaults.printify.require_shop_id()
            printify_client.delete_product(shop_id, str(product_id))


def _ok(response: Any, status: int = 200) -> Any:  # noqa: ANN401 - httpx response, JSON body
    assert response.status_code == status, response.text
    return response.json()


def _run(client: TestClient, body: dict[str, Any]) -> dict[str, Any]:
    """Start a plan or apply run and read its event stream to the end --
    the stream closes once the run has finished -- then its detail."""
    run_id = _ok(client.post("/api/runs", json=body), 202)["id"]
    streamed = client.get(f"/api/runs/{run_id}/events")
    assert streamed.status_code == 200, streamed.text
    detail: dict[str, Any] = _ok(client.get(f"/api/runs/{run_id}"))
    return detail


def _row(client: TestClient, batch_id: str) -> dict[str, Any]:
    rows: list[dict[str, Any]] = _ok(client.get(f"/api/batches/{batch_id}"))["rows"]
    assert len(rows) == 1, rows
    return rows[0]


def test_a_batch_created_listing_deploys_and_its_proposal_goes(
    client: TestClient, workspace: Workspace, etsy_client: HttpEtsyListingClient
) -> None:
    # The fixture listing, saved as a listing template (PR 1).
    saved = _ok(
        client.post(
            "/api/listing-templates",
            json={"name": LISTING_TEMPLATE, "from_listing": FIXTURE_LISTING},
        )
    )
    assert saved["saved"] is True, saved

    # One print-size design, staged and confirmed (PR 2).
    staged = _ok(
        client.post(
            "/api/staging",
            data={"listing_template": LISTING_TEMPLATE},
            files=[("files", (f"{DESIGN}.png", png(7, size=PRINT_AREA), "image/png"))],
        )
    )
    batch_id = _ok(client.post(f"/api/staging/{staged['id']}/confirm"))["id"]
    assert _row(client, batch_id)["name"] == DESIGN

    # The queue drafts the brief, researches the market and caches a
    # proposal (PR 3, PR 4).
    wait_for(lambda: _row(client, batch_id)["ai"] in {"done", "failed"}, timeout=AI_SECONDS)
    row = _row(client, batch_id)
    assert row["ai"] == "done", row
    proposal = _ok(client.get(f"/api/listings/{DESIGN}/proposal"))
    title = proposal["proposal"]["titles"][0]
    lead = proposal["proposal"]["description_leads"][0]

    # Accept the first title and lead, as the editor's drawers do: an
    # autosave PATCH with the concrete values, then the resolution. The
    # `etsy:` block merges one level deep, so the description is sent whole.
    document = yaml.safe_load(workspace.listing_file(DESIGN).read_text(encoding="utf-8"))
    description = dict(document["etsy"].get("description") or {})
    description["lead"] = lead
    _ok(
        client.patch(
            f"/api/listings/{DESIGN}", json={"etsy": {"title": title, "description": description}}
        )
    )
    _ok(
        client.patch(
            f"/api/listings/{DESIGN}/proposal/resolution",
            json={
                "generated_at": proposal["generated_at"],
                "title": "accepted",
                "lead": "accepted",
            },
        )
    )

    # Plan, then apply what was reviewed -- the deploy view's two runs.
    plan = _run(client, {"kind": "plan", "scope": "listings", "listings": [DESIGN]})
    assert plan["phase"] == "ready", plan
    planned = next(e for e in plan["events"] if e["type"] == "listing_planned")
    blocked = [
        (sp["stage"], sp["outcome"]["message"])
        for sp in planned["plan"]["stage_plans"]
        if sp["outcome"]["type"] == "blocked"
    ]
    assert not blocked, f"a stage refused, so this deploy tested less than it appears to: {blocked}"
    applied = _run(
        client,
        {
            "kind": "apply",
            "scope": "listings",
            "listings": [DESIGN],
            "expect": {DESIGN: planned["fingerprint"]},
        },
    )
    assert applied["phase"] == "applied", applied

    lock = Lockfile.read(workspace.lock_file(DESIGN))
    assert lock is not None
    assert lock.incomplete is None
    assert {"render", "printify_product", "publish", "etsy_listing", "etsy_media"} <= set(
        lock.applied
    )
    live = etsy_client.get_listing(int(lock.remote[ETSY_LISTING_ID_KEY]))
    assert live is not None
    assert live.title == title
    assert live.state == "draft"

    # A44: the UI apply's full success removed the proposal. The batch
    # record and its row stay, and deploying never marks a row reviewed.
    assert client.get(f"/api/listings/{DESIGN}/proposal").status_code == 404
    row = _row(client, batch_id)
    assert row["ai"] == "done"
    assert row["reviewed"] is False

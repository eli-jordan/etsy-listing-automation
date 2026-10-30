"""A run reads one ``shop.yaml`` from start to finish.

The Admin page's save replaces ``workspace.defaults`` in the running server
(``shop_settings.edit_shop``), and engine stages read
``ctx.workspace.defaults`` throughout a run. So a plan or apply run, and a
batch's listing creation, each capture the defaults when they start: an
in-flight run keeps the values it started with, and the next one sees the
edit.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from etsy_listings.core.application import shop_settings
from etsy_listings.core.application.deploy.events import TERMINAL_PHASES
from etsy_listings.core.application.deploy.executor import RunExecutor
from etsy_listings.core.application.deploy.registry import (
    ListingApply,
    ListingPlan,
    Run,
    RunRegistry,
)
from etsy_listings.core.batches import BatchStore, StagingStore, confirm, creation, stage_pngs
from etsy_listings.core.clients.printify.fakes import FakeCatalogClient
from etsy_listings.core.config.defaults import Defaults
from etsy_listings.core.engine.context import EventSink, RunContext
from etsy_listings.core.workspace.workspace import Workspace

from tests.support.batches import a_listing_template, png, uploads
from tests.support.builders import FIXTURE_LISTING


def _edit_currency(workspace: Workspace, currency: str) -> None:
    revision = shop_settings.read_shop(workspace).revision
    shop_settings.edit_shop(
        workspace, expected_revision=revision, changes={"etsy.currency": currency}
    )


def _wait(run: Run) -> None:
    deadline = time.monotonic() + 30
    while run.phase not in TERMINAL_PHASES:
        if time.monotonic() > deadline:
            pytest.fail(f"run stuck at {run.phase!r}")
        time.sleep(0.02)


@pytest.mark.parametrize("kind", ["plan", "apply"])
def test_a_run_keeps_the_shop_it_started_with(workspace_root: Path, kind: str) -> None:
    live = Workspace.discover(root_override=workspace_root)
    seen: list[RunContext] = []

    def context(workspace: Workspace, on_event: EventSink | None) -> RunContext:
        ctx = RunContext(
            workspace=workspace, catalog=FakeCatalogClient([], {}, {}), printify=None, etsy=None
        )
        seen.append(ctx)
        if len(seen) == 1:
            # The seller saves on the Admin page while this run is under way.
            _edit_currency(live, "EUR")
        return ctx

    executor = RunExecutor(workspace=live, context_factory=context, registry=RunRegistry())
    executor.start()
    try:
        command = (
            ListingPlan((FIXTURE_LISTING,))
            if kind == "plan"
            else ListingApply((FIXTURE_LISTING,), {})
        )
        first = executor.registry.create(command)
        assert isinstance(first, Run)
        _wait(first)
        second = executor.registry.create(command)
        assert isinstance(second, Run)
        _wait(second)
    finally:
        executor.stop()

    assert live.defaults.etsy.currency == "EUR"
    assert seen[0].workspace.defaults.etsy.currency == "NOK"
    assert seen[0].workspace is not live
    assert seen[-1].workspace.defaults.etsy.currency == "EUR"


def test_a_batch_creates_every_row_against_the_shop_it_started_with(
    workspace_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The template's prices are NOK. Switching the shop to EUR halfway
    through must not fail the rows still to create."""
    live = Workspace.discover(root_override=workspace_root)
    a_listing_template(live)
    staging, batches = StagingStore(live), BatchStore(live)
    designs = (("one.png", png(1)), ("two.png", png(2)), ("three.png", png(3)))
    session = stage_pngs(live, staging, "heavyweight-tee", uploads(*designs)).id
    real = creation._create
    currencies: list[str] = []

    def create(workspace: Workspace, *args: object, **kwargs: object) -> object:
        currencies.append(workspace.defaults.etsy.currency)
        row = real(workspace, *args, **kwargs)  # type: ignore[arg-type]
        if len(currencies) == 1:
            live.defaults = Defaults.model_validate(
                {
                    **live.defaults.model_dump(),
                    "etsy": {**live.defaults.etsy.model_dump(), "currency": "EUR"},
                }
            )
        return row

    monkeypatch.setattr(creation, "_create", create)

    batch = confirm(live, staging, batches, session)

    assert currencies == ["NOK", "NOK", "NOK"]
    assert [row.creation for row in batch.rows] == ["created"] * 3

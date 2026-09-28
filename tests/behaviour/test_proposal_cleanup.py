"""A44: a listing's cached proposal goes once it is fully applied (spec,
*Deployment interaction*; PRD 74).

*Full success* is three things at once: the listing's outcome is ``ok``, no
stage of its plan was blocked, and its lockfile carries no ``incomplete``
marker. ``ok`` alone is not enough -- a blocked stage is not a failure, so a
listing that deployed nothing to Etsy still reads ``ok``. The rule lives in
``engine/run.py``, so every entry point that applies gets it; these drive
``apply_listings`` directly, as both the CLI and the UI's executor do.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from etsy_listings.cli import app as cli_app
from etsy_listings.clients.etsy.transport import EtsyApiError
from etsy_listings.clients.printify.fakes import FakePrintifyClient
from etsy_listings.engine.context import EventSink, RunContext
from etsy_listings.engine.events import EngineRunEvent, EngineStageApplying
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.run import apply_listings, fully_applied, plan_listings
from etsy_listings.ui.api.app import create_app
from etsy_listings.workspace.workspace import Workspace

from tests.support.ai_runs import has_proposal, seed_proposal
from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import a_context, a_lock
from tests.support.pipeline import a_deployable_context, real_stages


def test_a_full_apply_removes_the_listing_s_proposal(workspace_root: Path) -> None:
    ctx = a_deployable_context(workspace_root)
    seed_proposal(workspace_root)

    report = apply_listings(ctx, [LISTING], real_stages())

    assert report.outcomes[0].ok, report.outcomes[0].error
    assert not has_proposal(workspace_root)


def test_cli_apply_removes_the_proposal_after_a_full_success(
    workspace_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The CLI does nothing about AI work (A43) but gets the cleanup all the
    same, because the cleanup is the engine's: ``cli/app.py`` has no
    proposal code, only the context it hands ``apply_listings``."""
    ctx = a_deployable_context(workspace_root)
    monkeypatch.setattr(
        cli_app.connections,
        "run_context",
        lambda _workspace, on_event=None: replace(ctx, on_event=on_event or ctx.on_event),
    )
    monkeypatch.setattr(cli_app, "STAGES", real_stages())
    seed_proposal(workspace_root)

    result = CliRunner().invoke(cli_app.app, ["apply", LISTING, "--root", str(workspace_root)])

    assert result.exit_code == 0, result.output
    assert not has_proposal(workspace_root)


def test_ui_apply_removes_the_proposal_after_a_full_success(workspace_root: Path) -> None:
    """The same engine call behind the runs resource: a CLI apply and a UI
    apply leave the same proposal state (spec, *Deployment interaction*)."""
    ctx = a_deployable_context(workspace_root)
    seed_proposal(workspace_root)

    def contexts(_workspace: Workspace, on_event: EventSink | None) -> RunContext:
        return replace(ctx, on_event=on_event) if on_event is not None else ctx

    app = create_app(ctx.workspace, context_factory=contexts)
    with TestClient(app) as client:
        started = client.post(
            "/api/runs",
            json={"kind": "apply", "scope": "listings", "listings": [LISTING], "expect": {}},
        )
        assert started.status_code == 202, started.text
        run_id = started.json()["id"]
        client.get(f"/api/runs/{run_id}/events")  # the stream ends with the run
        assert client.get(f"/api/runs/{run_id}").json()["phase"] == "applied"
        assert client.get(f"/api/listings/{LISTING}/proposal").status_code == 404

    assert not has_proposal(workspace_root)


def test_an_ok_apply_with_a_blocked_stage_keeps_the_proposal(workspace_root: Path) -> None:
    """The fixture workspace has no Printify shop, so `render` applies and
    every stage after it is blocked: ``ok``, and nothing reached Etsy."""
    seed_proposal(workspace_root)

    report = apply_listings(
        a_context(workspace_root, printify=FakePrintifyClient([])), [LISTING], real_stages()
    )

    outcome = report.outcomes[0]
    assert outcome.ok, outcome.error
    assert outcome.planned is not None
    assert any(sp.blocked for sp in outcome.planned.plan.stage_plans)
    assert has_proposal(workspace_root)


def _etsy_refuses_patches(ctx: RunContext, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*args: object, **kwargs: object) -> None:
        raise EtsyApiError(500, error="Etsy is down")

    monkeypatch.setattr(ctx.require_etsy(), "update_listing", refuse)


def test_a_failed_apply_keeps_the_proposal(
    workspace_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctx = a_deployable_context(workspace_root)
    _etsy_refuses_patches(ctx, monkeypatch)
    seed_proposal(workspace_root)

    report = apply_listings(ctx, [LISTING], real_stages())

    assert not report.outcomes[0].ok
    assert has_proposal(workspace_root)


def test_an_ok_apply_that_leaves_the_incomplete_marker_keeps_the_proposal(
    workspace_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed apply marks the lockfile incomplete (A29). A retry that
    returns ``ok`` without walking every stage -- stopped at a stage
    boundary, as a server shutdown stops one -- leaves the marker set."""
    ctx = a_deployable_context(workspace_root)
    with monkeypatch.context() as patched:
        _etsy_refuses_patches(ctx, patched)
        apply_listings(ctx, [LISTING], real_stages())
    seed_proposal(workspace_root)
    stages = {"started": 0}

    def stop_after_render(event: EngineRunEvent) -> None:
        if isinstance(event, EngineStageApplying):
            stages["started"] += 1

    report = apply_listings(
        ctx,
        [LISTING],
        real_stages(),
        on_event=stop_after_render,
        should_stop=lambda: stages["started"] > 0,
    )

    assert report.outcomes[0].ok, report.outcomes[0].error
    lock = Lockfile.read(ctx.workspace.lock_file(LISTING))
    assert lock is not None
    assert lock.incomplete is not None
    assert has_proposal(workspace_root)


def test_full_success_needs_the_marker_clear_whatever_else_holds(workspace_root: Path) -> None:
    """The marker is A44's third condition on its own: the same ``ok``,
    unblocked outcome is a full success with a clean lockfile and is not
    with a marked one."""
    ctx = a_deployable_context(workspace_root)
    outcome = plan_listings(ctx, [LISTING], real_stages()).outcomes[0]
    assert outcome.planned is not None
    assert not any(sp.blocked for sp in outcome.planned.plan.stage_plans)

    assert fully_applied(outcome, a_lock())
    assert not fully_applied(outcome, a_lock().marked_incomplete("etsy_listing"))

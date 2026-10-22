"""ADR-0050: a listing's cached proposal goes once it is fully applied (spec,
*Deployment interaction*; ADR-0047).

*Full success* is three things at once: the listing's outcome is ``ok``, no
stage of its plan was blocked, and its lockfile carries no ``incomplete``
marker. ``ok`` alone is not enough -- a blocked stage is not a failure, so a
listing that deployed nothing to Etsy still reads ``ok``. The rule lives in
``engine/run.py``, so every entry point that applies gets it. The predicate's
cases are tabulated in ``tests/core/unit/test_fully_applied.py``; here simple
stages prove which outcomes physically remove the proposal, and the real
pipeline is kept for one full success, the CLI and HTTP wiring, and a stop
after the last runnable stage.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import BaseModel, ConfigDict
from typer.testing import CliRunner

from etsy_listings.cli import app as cli_app
from etsy_listings.core.engine.change import Verdict
from etsy_listings.core.engine.context import EventSink, RunContext
from etsy_listings.core.engine.events import EngineRunEvent, EngineStageApplying
from etsy_listings.core.engine.lock import Lockfile
from etsy_listings.core.engine.run import ListingOutcome, apply_listings, plan_listings
from etsy_listings.core.engine.stage import StageApplyResult
from etsy_listings.core.errors import UserFacingError
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.app import create_app

from tests.support.ai_runs import has_proposal, seed_proposal
from tests.support.builders import FIXTURE_LISTING as LISTING
from tests.support.builders import a_context
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
    """The CLI does nothing about AI work but gets the cleanup all the
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


class _Applied(BaseModel):
    model_config = ConfigDict(extra="ignore")


@dataclass
class _Stage:
    """A stage that works, refuses, raises or idles on request: the subject is
    which outcomes physically remove a proposal, not what any real stage does."""

    name: str
    local: bool = True
    group: str | None = None
    applied_model: type[_Applied] = _Applied
    verdict: str = "work"
    fails: bool = False

    def desired(self, ctx: RunContext, listing: str, applied: _Applied | None) -> str:
        return self.name

    def read_live(self, ctx: RunContext, listing: str, lock: Lockfile, applied: object) -> None:
        return None

    def plan(self, desired: object, applied: object, live: object) -> Verdict:
        if self.verdict == "refused":
            return Verdict.refused(f"{self.name} cannot run")
        if self.verdict == "idle":
            return Verdict.no_work()
        return Verdict.work(f"{self.name} has work")

    def apply(
        self, ctx: RunContext, desired: object, applied: object, live: object, lock: Lockfile
    ) -> StageApplyResult:
        if self.fails:
            raise UserFacingError(f"{self.name} refused")
        return StageApplyResult(applied={})


def _apply_simple(root: Path, *stages: _Stage, **kwargs: Any) -> ListingOutcome:
    seed_proposal(root)
    return apply_listings(a_context(root), [LISTING], list(stages), **kwargs).outcomes[0]


def test_a_simple_full_success_removes_the_proposal(workspace_root: Path) -> None:
    outcome = _apply_simple(workspace_root, _Stage("render"), _Stage("etsy", verdict="idle"))

    assert outcome.ok, outcome.error
    assert not has_proposal(workspace_root)


def test_an_ok_apply_with_a_blocked_stage_keeps_the_proposal(workspace_root: Path) -> None:
    """A blocked stage is not a failure: ``ok``, yet nothing reached it."""
    outcome = _apply_simple(workspace_root, _Stage("render"), _Stage("etsy", verdict="refused"))

    assert outcome.ok, outcome.error
    assert has_proposal(workspace_root)


def test_a_failed_apply_keeps_the_proposal(workspace_root: Path) -> None:
    outcome = _apply_simple(workspace_root, _Stage("render"), _Stage("etsy", fails=True))

    assert not outcome.ok
    assert has_proposal(workspace_root)


def test_an_ok_apply_that_leaves_the_incomplete_marker_keeps_the_proposal(
    workspace_root: Path,
) -> None:
    """A failed apply marks the lockfile incomplete. A retry that returns
    ``ok`` without walking every stage -- stopped at a stage boundary, as a
    server shutdown stops one -- leaves the marker set."""
    stages = (_Stage("render"), _Stage("etsy", fails=True))
    assert not _apply_simple(workspace_root, *stages).ok
    started: list[str] = []

    def count(event: EngineRunEvent) -> None:
        if isinstance(event, EngineStageApplying):
            started.append(event.stage)

    retried = _apply_simple(
        workspace_root,
        _Stage("render"),
        _Stage("etsy"),
        on_event=count,
        should_stop=lambda: bool(started),
    )

    assert retried.ok, retried.error
    lock = Lockfile.read(a_context(workspace_root).workspace.lock_file(LISTING))
    assert lock is not None and lock.incomplete is not None
    assert has_proposal(workspace_root)


def test_a_stop_after_the_last_runnable_stage_still_removes_the_proposal(
    workspace_root: Path,
) -> None:
    """A stop observed at a trailing no-op skipped no deploy work, so ADR-0050's
    three full-success conditions still remove the deployed proposal."""
    ctx = a_deployable_context(workspace_root)
    first = apply_listings(ctx, [LISTING], real_stages())
    assert first.outcomes[0].ok, first.outcomes[0].error
    ctx.workspace.render_file(LISTING, "flat-lay-01", "black").unlink()
    seed_proposal(workspace_root)
    planned = plan_listings(ctx, [LISTING], real_stages()).outcomes[0].planned
    assert planned is not None
    runnable = sum(stage.will_run for stage in planned.plan.stage_plans)
    assert 0 < runnable < len(planned.plan.stage_plans)
    started = {"count": 0}

    def count_started(event: EngineRunEvent) -> None:
        if isinstance(event, EngineStageApplying):
            started["count"] += 1

    def stop_after_last_runnable_stage() -> bool:
        return started["count"] == runnable

    report = apply_listings(
        ctx,
        [LISTING],
        real_stages(),
        on_event=count_started,
        should_stop=stop_after_last_runnable_stage,
    )

    assert report.outcomes[0].ok, report.outcomes[0].error
    assert not has_proposal(workspace_root)

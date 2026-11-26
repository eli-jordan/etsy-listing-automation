"""The runs resource: each write is a call into
:class:`~etsy_listings.core.application.deploy.deployments.Deployments`, and this
module only turns requests into run commands and answers into HTTP."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, assert_never

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

from etsy_listings.core.application import batch_workflow
from etsy_listings.core.application.deploy.deployments import Deployments
from etsy_listings.core.application.deploy.events import RunScope
from etsy_listings.core.application.deploy.registry import (
    BatchApply,
    BatchPlan,
    Conflict,
    ListingApply,
    ListingPlan,
    Run,
    RunCommand,
    WorkspaceApply,
    WorkspacePlan,
)
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api import app_state
from etsy_listings.server.api.refusal_status import Refusal, refusals
from etsy_listings.server.api.schemas import (
    ApplyRunDetail,
    ApplyRunSummary,
    BatchApplyRequest,
    BatchPlanRequest,
    CreateRunRequest,
    ListingApplyRequest,
    ListingPlanRequest,
    PlanRunDetail,
    PlanRunSummary,
    RunConflict,
    RunDetail,
    RunSummary,
    WorkspaceApplyRequest,
    WorkspacePlanRequest,
)
from etsy_listings.server.api.sse import event_stream

router = APIRouter(prefix="/api/runs", tags=["runs"])

"""How long one SSE poll blocks the executor thread pool before yielding
control back to the event loop -- short enough that a client disconnecting,
or the surrounding server shutting down, is noticed promptly; long enough that
an idle stream is not a busy loop."""


def _deployments(request: Request) -> Deployments:
    deployments: Deployments = request.app.state.deployments
    return deployments


@dataclass(frozen=True)
class Target:
    deployments: Deployments
    run: Run


def target(request: Request, run_id: str) -> Target:
    deployments = _deployments(request)
    run = deployments.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail=f"no run {run_id!r}")
    return Target(deployments=deployments, run=run)


def _summary(run: Run, deployments: Deployments) -> RunSummary:
    waiting = deployments.waiting_for_backup(run)
    if run.kind == "plan":
        return PlanRunSummary(
            id=run.id,
            kind="plan",
            scope=run.scope,
            batch_id=run.batch_id,
            listings=list(run.listings),
            phase=run.plan_phase,
            seen=run.seen,
            created_at=run.created_at,
            publish=run.publish,
            waiting_for_backup=waiting,
        )
    return ApplyRunSummary(
        id=run.id,
        kind="apply",
        scope=run.scope,
        batch_id=run.batch_id,
        listings=list(run.listings),
        phase=run.apply_phase,
        seen=run.seen,
        reviewed_run_id=run.reviewed_run_id,
        created_at=run.created_at,
        publish=run.publish,
        waiting_for_backup=waiting,
    )


def _detail(run: Run, deployments: Deployments) -> RunDetail:
    summary = _summary(run, deployments)
    if isinstance(summary, PlanRunSummary):
        return PlanRunDetail(**summary.model_dump(), events=list(run.events))
    return ApplyRunDetail(**summary.model_dump(), events=list(run.events))


@router.post(
    "",
    status_code=202,
    response_model=RunSummary,
    responses={
        **refusals({404: "No such batch"}),
        409: {
            "model": RunConflict | Refusal,
            "description": "The run already holding one of these listings, to reattach to; or "
            "an apply that is not exactly its review, or a batch plan with nothing to deploy",
        },
    },
)
def create_run(request: Request, body: CreateRunRequest) -> RunSummary | JSONResponse:
    """Queue a plan or apply run."""
    deployments = _deployments(request)
    result = deployments.submit(_run_command(request, body))
    if isinstance(result, Conflict):
        return JSONResponse(status_code=409, content={"active_run": result.active_run})
    return _summary(result, deployments)


def _run_command(request: Request, body: CreateRunRequest) -> RunCommand:
    workspace: Workspace = request.app.state.workspace
    match body:
        case ListingPlanRequest():
            return ListingPlan(tuple(body.listings), publish=body.publish)
        case WorkspacePlanRequest():
            return WorkspacePlan(tuple(workspace.listing_names()), publish=body.publish)
        case BatchPlanRequest():
            listings = batch_workflow.batch_deploy_listings(
                workspace, app_state.batch_store(request), body.batch_id
            )
            return BatchPlan(body.batch_id, listings, publish=body.publish)
        case ListingApplyRequest():
            return ListingApply(tuple(body.listings), body.expect, publish=body.publish)
        case BatchApplyRequest():
            return BatchApply(
                body.batch_id,
                tuple(body.listings),
                body.expect,
                body.reviewed_run_id,
                publish=body.publish,
            )
        case WorkspaceApplyRequest():
            return WorkspaceApply(
                tuple(body.listings), body.expect, body.reviewed_run_id, publish=body.publish
            )
        case _:
            assert_never(body)


@router.get("", response_model=list[RunSummary])
def list_runs(
    request: Request,
    listing: str | None = None,
    scope: RunScope | None = None,
    batch: str | None = None,
) -> list[RunSummary]:
    """``listing`` narrows to that listing's current run (active, or finished
    and not yet superseded); ``scope=batch&batch=`` to that listing batch's.
    Omitted, every run this process still remembers."""
    deployments = _deployments(request)
    runs = deployments.runs(listing=listing, scope=scope, batch=batch)
    return [_summary(run, deployments) for run in runs]


@router.get("/{run_id}", response_model=RunDetail)
def get_run(target: Annotated[Target, Depends(target)]) -> RunDetail:
    return _detail(target.run, target.deployments)


@router.delete(
    "/{run_id}",
    response_model=RunSummary,
    responses=refusals({404: "No such run", 409: "An apply, or a finished run"}),
)
def cancel_run(target: Annotated[Target, Depends(target)]) -> RunSummary:
    """Cancel a queued or running plan. Leaving the page never cancels an
    apply."""
    result = target.deployments.cancel(target.run.id)
    if result == "refused":
        raise HTTPException(status_code=409, detail="this run cannot be cancelled")
    return _summary(target.run, target.deployments)


@router.post("/{run_id}/seen", response_model=RunSummary)
def mark_seen(target: Annotated[Target, Depends(target)]) -> RunSummary:
    target.run.mark_seen()
    return _summary(target.run, target.deployments)


@router.get("/{run_id}/events")
def stream_events(
    target: Annotated[Target, Depends(target)], request: Request
) -> StreamingResponse:
    """``text/event-stream`` over this run's own event buffer -- every event
    already recorded past ``Last-Event-ID``, then whatever the worker thread
    appends next, until the run reaches a terminal phase."""
    return event_stream(request, target.run, lambda event: event.id)

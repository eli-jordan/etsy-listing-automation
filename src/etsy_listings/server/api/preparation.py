"""Thin HTTP adapters for durable preparation and calibration masks."""

import time
from collections.abc import AsyncIterator
from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool
from starlette.responses import StreamingResponse

from etsy_listings.core.application.preparation.coordinator import PreparationRefused, Preparations
from etsy_listings.core.application.preparation.models import TERMINAL, Event, Job
from etsy_listings.core.application.preparation_views import preparation_view, read_mask
from etsy_listings.core.application.refusals import TemplateMissing
from etsy_listings.core.config.errors import ConfigLoadError
from etsy_listings.core.errors import UserFacingError
from etsy_listings.core.workspace.calibration import CalibrationConflict, CalibrationStore
from etsy_listings.server.api.schemas import (
    CreatePreparationRequest,
    MapReadinessResponse,
    MarigoldRuntimeResponse,
    MaskHistoryResponse,
    MaskHistoryStroke,
    PreparationJobResponse,
    PreparationPlacementResponse,
    PreparationResponse,
    PreparationResyncResponse,
)

router = APIRouter(prefix="/api", tags=["preparation"])


def coordinator(request: Request) -> Preparations:
    value: Preparations = request.app.state.preparations
    return value


def job_response(preparations: Preparations, job: Job) -> PreparationJobResponse:
    queued = [item.id for item in preparations.list_jobs(limit=1000) if item.phase == "queued"]
    return PreparationJobResponse(
        id=job.id,
        template=job.template,
        kind=job.kind,
        phase=job.phase,
        step=job.step,
        elapsed=max(0, (job.updated if job.phase in TERMINAL else time.time()) - job.created),
        placements_completed=job.placements_completed,
        placements_total=len(job.snapshot.placements),
        error=job.error,
        last_event_sequence=job.last_event_sequence,
        queue_position=queued.index(job.id) + 1 if job.id in queued else None,
        engine_version=job.engine_version,
    )


@router.get("/templates/{name}/preparation", response_model=PreparationResponse)
def status(request: Request, name: str) -> PreparationResponse:
    preparations = coordinator(request)
    try:
        view = preparation_view(preparations, name)
    except (TemplateMissing, ConfigLoadError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except UserFacingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return PreparationResponse(
        template=view.template,
        config_revision=view.config_revision,
        main_photo=view.main_photo,
        maps=MapReadinessResponse(**asdict(view.maps), can_render=view.maps.can_render),
        placements=[PreparationPlacementResponse(**asdict(item)) for item in view.placements],
        active_job=job_response(preparations, view.active_job) if view.active_job else None,
        latest_job=job_response(preparations, view.latest_job) if view.latest_job else None,
        renderer_settings=view.renderer_settings,
        prepared_engine=view.prepared_engine,
    )


@router.get("/preparation/jobs", response_model=list[PreparationJobResponse])
def jobs(
    request: Request,
    template: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
) -> list[PreparationJobResponse]:
    preparations = coordinator(request)
    if template is not None:
        preparations.workspace.template_dir(template)
    return [
        job_response(preparations, job)
        for job in preparations.list_jobs(template=template, offset=offset, limit=limit)
    ]


def mask_response(
    request: Request, name: str, placement_id: str | None, source: Literal["edited", "automatic"]
) -> Response:
    try:
        mask = read_mask(coordinator(request).workspace, name, placement_id)
    except TemplateMissing as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UserFacingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return Response(
        mask.edited if source == "edited" else mask.automatic,
        media_type="image/png",
        headers={"Cache-Control": "no-cache", "ETag": mask.checksum},
    )


@router.get("/templates/{name}/mask")
def mask(
    request: Request, name: str, source: Literal["edited", "automatic"] = "edited"
) -> Response:
    return mask_response(request, name, None, source)


@router.get("/templates/{name}/placements/{placement_id}/mask")
def placement_mask(
    request: Request,
    name: str,
    placement_id: str,
    source: Literal["edited", "automatic"] = "edited",
) -> Response:
    return mask_response(request, name, placement_id, source)


def history_response(request: Request, name: str, placement_id: str | None) -> MaskHistoryResponse:
    try:
        mask = read_mask(coordinator(request).workspace, name, placement_id)
    except TemplateMissing as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except UserFacingError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    store = CalibrationStore(coordinator(request).workspace)
    strokes = store.history(name, placement_id, mask.checksum)
    return MaskHistoryResponse(
        checksum=mask.checksum,
        undo_count=mask.undo_count,
        strokes=[MaskHistoryStroke.model_validate(stroke) for stroke in strokes],
    )


@router.get("/templates/{name}/mask-history", response_model=MaskHistoryResponse)
def mask_history(request: Request, name: str) -> MaskHistoryResponse:
    return history_response(request, name, None)


@router.get(
    "/templates/{name}/placements/{placement_id}/mask-history", response_model=MaskHistoryResponse
)
def placement_history(request: Request, name: str, placement_id: str) -> MaskHistoryResponse:
    return history_response(request, name, placement_id)


@router.get("/marigold/runtime", response_model=MarigoldRuntimeResponse)
def runtime_status(request: Request) -> MarigoldRuntimeResponse:
    capability = coordinator(request).runtime.inspect()
    return MarigoldRuntimeResponse(
        available=capability.available,
        problem=capability.problem,
        engine_version=capability.engine_version,
        required_engine=capability.required_engine,
        installation_id=capability.installation_id,
        update_available=capability.update_available,
        max_num_inference_steps=capability.max_num_inference_steps,
        max_ensemble_size=capability.max_ensemble_size,
        max_image_dimension=capability.max_image_dimension,
    )


@router.post("/preparation/jobs", response_model=PreparationJobResponse, status_code=202)
def submit(request: Request, body: CreatePreparationRequest) -> PreparationJobResponse:
    preparations = coordinator(request)
    try:
        job = preparations.submit(
            body.template,
            config_revision=body.config_revision,
            request_id=body.request_id,
            action=body.action,
            previous_job=body.previous_job,
            reset_masks_for_photo=body.reset_masks_for_photo,
        )
    except CalibrationConflict as exc:
        raise HTTPException(status_code=412, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        if isinstance(exc, PreparationRefused):
            raise HTTPException(
                status_code=409, detail={"reason": "preparation_refused", "message": str(exc)}
            ) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except UserFacingError as exc:
        raise HTTPException(
            status_code=409, detail={"reason": "preparation_refused", "message": str(exc)}
        ) from exc
    return job_response(preparations, job)


def existing_job(preparations: Preparations, identity: str) -> Job:
    try:
        return preparations.status(identity)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Preparation job not found") from exc


@router.get("/preparation/jobs/{identity}", response_model=PreparationJobResponse)
def job_status(request: Request, identity: str) -> PreparationJobResponse:
    preparations = coordinator(request)
    return job_response(preparations, existing_job(preparations, identity))


@router.delete("/preparation/jobs/{identity}", response_model=PreparationJobResponse)
def cancel(request: Request, identity: str) -> PreparationJobResponse:
    preparations = coordinator(request)
    existing_job(preparations, identity)
    return job_response(preparations, preparations.cancel(identity))


async def event_stream(
    request: Request, preparations: Preparations, identity: str, after: int, initial: Job | None
) -> AsyncIterator[bytes]:
    if initial is not None:
        after = initial.last_event_sequence
        snapshot = await run_in_threadpool(job_response, preparations, initial)
        yield f"id: {after}\nevent: snapshot\ndata: {snapshot.model_dump_json()}\n\n".encode()
    while not await request.is_disconnected():
        try:
            pending = await run_in_threadpool(preparations.events, identity, after=after, wait=1)
        except ValueError:
            yield b'event: resync\ndata: {"resync":true}\n\n'
            return
        for event in pending:
            after = event.sequence
            yield f"id: {after}\nevent: progress\ndata: {event.model_dump_json()}\n\n".encode()
        job = await run_in_threadpool(preparations.status, identity)
        if job.phase in TERMINAL and after >= job.last_event_sequence:
            return
        if not pending:
            yield b": keepalive\n\n"


@router.get(
    "/preparation/jobs/{identity}/events",
    responses={
        200: {
            "model": Event | PreparationJobResponse | PreparationResyncResponse,
            "content": {"text/event-stream": {}},
        }
    },
)
def events(request: Request, identity: str) -> StreamingResponse:
    preparations = coordinator(request)
    job = existing_job(preparations, identity)
    cursor = request.headers.get("Last-Event-ID")
    try:
        after = int(cursor) if cursor is not None else 0
        preparations.events(identity, after=after)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail={"resync": True, "message": str(exc)}) from exc
    return StreamingResponse(
        event_stream(request, preparations, identity, after, job if cursor is None else None),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

"""Typed reads of what ``create_app`` keeps on ``app.state``.

``app.state`` is untyped, so each read names the type it expects. The routers
share these instead of each declaring its own copy.
"""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import BackgroundTasks, Request

from etsy_listings.core.application.backup_coordinator import BackupCoordinator
from etsy_listings.core.application.dependencies import ClientFactories
from etsy_listings.core.application.job_gate import JobGate
from etsy_listings.core.application.position_coverage import (
    cover_recalibrated,
    cover_widened_limits,
)
from etsy_listings.core.application.preparation.coordinator import Preparations
from etsy_listings.core.batches import BatchStore, StagingStore
from etsy_listings.core.render.positions import PositionLimits
from etsy_listings.core.workspace.workspace import Workspace


def workspace(request: Request) -> Workspace:
    value: Workspace = request.app.state.workspace
    return value


def staging_store(request: Request) -> StagingStore:
    value: StagingStore = request.app.state.staging_store
    return value


def batch_store(request: Request) -> BatchStore:
    value: BatchStore = request.app.state.batch_store
    return value


def clients(request: Request) -> ClientFactories:
    value: ClientFactories = request.app.state.clients
    return value


def job_gate(request: Request) -> JobGate:
    value: JobGate = request.app.state.job_gate
    return value


def backups(request: Request) -> BackupCoordinator:
    value: BackupCoordinator = request.app.state.backups
    return value


@dataclass(frozen=True)
class AfterResponse:
    """Preparation work a request starts. Coverage is queued to run once the
    response has gone, so a slow template scan never holds it."""

    preparations: Preparations
    background: BackgroundTasks

    def cover_recalibrated(self, template: str) -> None:
        self.background.add_task(cover_recalibrated, self.preparations, template)

    def cover_widened(self, saved: PositionLimits, limits: PositionLimits) -> None:
        self.background.add_task(cover_widened_limits, self.preparations, saved, limits)


def after_response(request: Request, background: BackgroundTasks) -> AfterResponse:
    preparations: Preparations = request.app.state.preparations
    return AfterResponse(preparations, background)

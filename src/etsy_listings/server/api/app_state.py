"""Typed reads of what ``create_app`` keeps on ``app.state``.

``app.state`` is untyped, so each read names the type it expects. The routers
share these instead of each declaring its own copy.
"""

from __future__ import annotations

from fastapi import Request

from etsy_listings.core.application.dependencies import ClientFactories
from etsy_listings.core.batches import BatchStore, StagingStore
from etsy_listings.core.workspace.workspace import Workspace


def workspace(request: Request) -> Workspace:
    """The workspace the app serves."""
    value: Workspace = request.app.state.workspace
    return value


def staging_store(request: Request) -> StagingStore:
    """The process's staging-session store."""
    value: StagingStore = request.app.state.staging_store
    return value


def batch_store(request: Request) -> BatchStore:
    """The process's batch-record store."""
    value: BatchStore = request.app.state.batch_store
    return value


def clients(request: Request) -> ClientFactories:
    """How the routes build the Etsy and Printify clients they ask through."""
    value: ClientFactories = request.app.state.clients
    return value

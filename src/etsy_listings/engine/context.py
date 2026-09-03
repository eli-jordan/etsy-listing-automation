"""``RunContext``: what a stage needs to compute desired/live state and apply.

Phase 0/1 only carry a workspace and a catalog client. Later phases (2: Printify,
3: Etsy, 6: rate limiting) extend this with the shop-scoped clients and the
shared token-bucket limiter from A3 -- added as new optional fields so existing
stages and tests are unaffected.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from etsy_listings.catalog.client import CatalogClient
from etsy_listings.workspace.workspace import Workspace

EventSink = Callable[[str], None]


def _noop_sink(message: str) -> None:
    return None


@dataclass
class RunContext:
    workspace: Workspace
    catalog: CatalogClient
    on_event: EventSink = field(default=_noop_sink)

    def emit(self, message: str) -> None:
        self.on_event(message)

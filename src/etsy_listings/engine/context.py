"""``RunContext``: what a stage needs to compute desired/live state and apply.

Phase 0/1 only carry a workspace and a catalog client. Later phases (2: Printify,
3: Etsy, 6: rate limiting) extend this with the shop-scoped clients and the
shared token-bucket limiter from A3 -- added as new optional fields so existing
stages and tests are unaffected.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from etsy_listings.clients.printify.protocol import CatalogClient, PrintifyClient
from etsy_listings.workspace.workspace import Workspace

Swatch = tuple[int, int, int]
"""An 8-bit sRGB colour a sink may render next to an event. Structured, not an
ANSI escape baked into the message: the CLI colours it, the UI's future SSE
serialiser sends it as JSON, and a log file gets neither."""


@dataclass(frozen=True)
class Event:
    """Progress reported by a stage while applying."""

    message: str
    swatches: tuple[Swatch, ...] = ()


EventSink = Callable[[Event], None]


def _noop_sink(event: Event) -> None:
    return None


@dataclass
class RunContext:
    workspace: Workspace
    catalog: CatalogClient
    printify: PrintifyClient | None = None
    """The shop-scoped client, from Phase 2 on. Optional because the stages
    that came before it do not need one, and a workspace that only renders
    mockups should not need a token to run `plan`."""
    on_event: EventSink = field(default=_noop_sink)

    def emit(self, message: str, *, swatches: Sequence[Swatch] = ()) -> None:
        self.on_event(Event(message=message, swatches=tuple(swatches)))

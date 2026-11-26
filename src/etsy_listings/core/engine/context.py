from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

from etsy_listings.core.clients.etsy.listings import EtsyListingClient
from etsy_listings.core.clients.printify.protocol import CatalogClient, PrintifyClient
from etsy_listings.core.workspace.workspace import Workspace


class MissingClientError(RuntimeError):
    """A stage ran without the client it needs.

    Deliberately not user-facing: every route that reaches a stage's ``apply``
    goes through a ``plan`` that would have blocked an unconfigured workspace
    first, so this can only be reached by wiring a run wrongly.
    """

    def __init__(self, service: str) -> None:
        super().__init__(
            f"this run has no {service} client, so a stage that needs one cannot run. "
            f"That is a wiring bug, not a configuration problem."
        )


Swatch = tuple[int, int, int]
"""An 8-bit sRGB colour a sink may render next to an event. Structured, not an
ANSI escape baked into the message: the CLI colours it, the UI's SSE
serialiser sends it as JSON, and a log file gets neither."""


@dataclass(frozen=True)
class Event:
    message: str
    swatches: tuple[Swatch, ...] = ()


EventSink = Callable[[Event], None]


def _noop_sink(_event: Event) -> None:
    return None


@dataclass
class RunContext:
    workspace: Workspace
    catalog: CatalogClient
    printify: PrintifyClient | None = None
    """Optional because a workspace that only renders mockups should not need
    a token to run `plan`."""
    etsy: EtsyListingClient | None = None
    """Optional for the same reason ``printify`` is: `plan` builds a context
    for a workspace that has never signed in to Etsy."""
    on_event: EventSink = field(default=_noop_sink)
    rewrites: Mapping[Path, Path | None] = field(default_factory=dict)
    """Local files an earlier stage in this plan will rewrite with different
    bytes when it applies, each mapped to a file already holding those bytes
    (a reviewed preview), or ``None`` when they do not exist yet.

    ``build_plan`` fills it from each stage that will run and declares
    ``rewrites()``, for the stages after it. A later stage that reads such a
    file at plan time is reading what is about to be replaced."""

    def emit(self, message: str, *, swatches: Sequence[Swatch] = ()) -> None:
        self.on_event(Event(message=message, swatches=tuple(swatches)))

    def with_event_sink(self, sink: EventSink) -> RunContext:
        current = self.on_event

        def emit(event: Event) -> None:
            current(event)
            sink(event)

        return replace(self, on_event=emit)

    def require_printify(self) -> PrintifyClient:
        if self.printify is None:
            raise MissingClientError("Printify")
        return self.printify

    def require_etsy(self) -> EtsyListingClient:
        if self.etsy is None:
            raise MissingClientError("Etsy")
        return self.etsy

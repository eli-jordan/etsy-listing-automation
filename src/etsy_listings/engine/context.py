"""``RunContext``: what a stage needs to compute desired/live state and apply.

Phase 0/1 only carry a workspace and a catalog client. Later phases (2: Printify,
3: Etsy, 6: rate limiting) extend this with the shop-scoped clients and the
shared token-bucket limiter from A3 -- added as new optional fields so existing
stages and tests are unaffected.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from etsy_listings.clients.etsy.listings import EtsyListingClient
from etsy_listings.clients.printify.protocol import CatalogClient, PrintifyClient
from etsy_listings.workspace.workspace import Workspace


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
    etsy: EtsyListingClient | None = None
    """The Etsy listing surface, from Phase 3 on -- `publish`'s poll target,
    `etsy_listing`'s PATCH, `etsy_media`'s uploads. Optional for the same
    reason ``printify`` is: `plan` builds a context for a workspace that has
    never signed in to Etsy, and demanding a client there would mean every
    Phase 1/2 workspace needs one to run `plan` at all."""
    on_event: EventSink = field(default=_noop_sink)

    def emit(self, message: str, *, swatches: Sequence[Swatch] = ()) -> None:
        self.on_event(Event(message=message, swatches=tuple(swatches)))

    def require_printify(self) -> PrintifyClient:
        """The shop-scoped client, or a loud failure.

        The optional field above is what lets `plan` build a context for a
        workspace that has never needed a token; a stage that has got as far
        as applying needs the client to actually be there. The unwrap lived in
        the product stage as a private helper with a bespoke error class, and
        every future stage that writes to Printify would have written the same
        one -- so it is here, once, beside the field it unwraps.

        A :class:`MissingClientError` and not a
        :class:`~etsy_listings.errors.UserFacingError`: reaching here means a
        stage the plan flagged was run without its client, which is a wiring
        defect and deserves the traceback a defect gets.
        """
        if self.printify is None:
            raise MissingClientError("Printify")
        return self.printify

    def require_etsy(self) -> EtsyListingClient:
        """The Etsy listing client, or a loud failure. Mirrors
        :meth:`require_printify` for the reason given there."""
        if self.etsy is None:
            raise MissingClientError("Etsy")
        return self.etsy

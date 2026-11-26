from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from collections.abc import Callable

from etsy_listings.core.application.job_gate import JobGate, Ticket
from etsy_listings.core.application.listing_reads import listing_scenes
from etsy_listings.core.application.position_fit_pruning import prune_position_fits
from etsy_listings.core.application.scene_previews import (
    DISK_IMAGES,
    SceneLayers,
    saved_scene,
)
from etsy_listings.core.config.listing import TemplateMediaEntry
from etsy_listings.core.errors import UserFacingError
from etsy_listings.core.workspace.workspace import Workspace

logger = logging.getLogger(__name__)

SKIPPED = (UserFacingError, ValueError, OSError)
"""What a scene that cannot be composed raises: the preview endpoint's
refusals (a template unprepared, missing or of another kind, a listing gone
or not loading), an unusable design, a file deleted in between. Anything
else is a bug, logged as one."""

Scene = tuple[str, str | None]
"""A gallery scene: its template and, for a colour-matrix one, its colour."""


def gallery_scenes(workspace: Workspace, name: str) -> list[Scene]:
    listing = workspace.load_listing(name)
    return [
        (entry.template, entry.colour)
        for entry in listing.media
        if isinstance(entry, TemplateMediaEntry)
    ]


def warm_scene(workspace: Workspace, name: str, template: str, colour: str | None) -> None:
    listing = listing_scenes(workspace, name)
    saved_scene(
        workspace,
        template,
        SceneLayers(colour, listing.artwork, listing.boxes(template)),
        size="full",
        images=DISK_IMAGES,
    )


class SceneWarmer:
    def __init__(
        self,
        workspace: Workspace,
        *,
        scenes: Callable[[Workspace, str], list[Scene]] = gallery_scenes,
        warm: Callable[[Workspace, str, str, str | None], None] = warm_scene,
        prune: Callable[[Workspace], object] = prune_position_fits,
        gate: JobGate | None = None,
    ) -> None:
        self._workspace = workspace
        self._gate = gate if gate is not None else JobGate()
        self._scenes = scenes
        self._warm = warm
        self._prune = prune
        self._wake = threading.Condition()
        self._queued: OrderedDict[str, None] = OrderedDict()
        self._stopping = False
        self._idle = threading.Event()
        self._idle.set()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._idle.clear()  # until the startup prune is done
        self._thread = threading.Thread(target=self._loop, name="scene-warmer", daemon=True)
        self._thread.start()

    def stop(self, *, timeout: float = 10.0) -> None:
        """A scene outlasting ``timeout`` is abandoned with the daemon thread."""
        with self._wake:
            self._stopping = True
            self._queued.clear()
            self._wake.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def request(self, name: str) -> None:
        with self._wake:
            if self._stopping:
                return
            self._queued.setdefault(name)
            self._idle.clear()
            self._wake.notify_all()

    def wait_idle(self, *, timeout: float) -> bool:
        return self._idle.wait(timeout)

    def _loop(self) -> None:
        startup = self._gate.wait_admit("Pruning position fits")
        if startup is not None:
            with startup:
                self._settle()
        while True:
            next_job = self._take()
            if next_job is None:
                with self._wake:
                    self._idle.set()
                return
            name, ticket = next_job
            with ticket:
                try:
                    self._warm_listing(name)
                except Exception:
                    logger.exception("warming listing %r's scenes failed", name)
                self._settle()

    def _take(self) -> tuple[str, Ticket] | None:
        """Only this thread pops the queue, so the name peeked here stays first."""
        while True:
            with self._wake:
                self._wake.wait_for(lambda: bool(self._queued) or self._stopping)
                if self._stopping:
                    return None
                name = next(iter(self._queued))
            ticket = self._gate.wait_admit(f"Scene warming for {name}")
            if ticket is None:
                return None
            with self._wake:
                if self._queued and not self._stopping:
                    return self._queued.popitem(last=False)[0], ticket
            ticket.release()

    def _settle(self) -> None:
        with self._wake:
            if self._queued:
                return
        try:
            self._prune(self._workspace)
        except Exception:
            logger.exception("pruning position fits failed")
        with self._wake:
            if not self._queued:
                self._idle.set()

    def _warm_listing(self, name: str) -> None:
        try:
            scenes = self._scenes(self._workspace, name)
        except SKIPPED as exc:
            logger.debug("not warming listing %r: %s", name, exc)
            return
        for template, colour in scenes:
            with self._wake:
                if self._stopping or name in self._queued:
                    return
            try:
                self._warm(self._workspace, name, template, colour)
            except SKIPPED as exc:
                logger.debug("not warming %r on %r for %r: %s", colour, template, name, exc)

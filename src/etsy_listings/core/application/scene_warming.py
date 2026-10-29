"""Compose a listing's gallery scenes in the background, so the Listing Images
tab finds them in the scene cache rather than waiting seconds per picture.

A save that leaves a listing with a template entry in ``media:`` asks
:meth:`SceneWarmer.request` for that listing. One worker thread then takes
each template entry through :func:`~etsy_listings.core.application.prepared_previews.saved_scene`
at full size -- the very path ``GET /api/listings/{name}/scene-preview``
takes -- so what it stores is under the identity that endpoint looks up, and
the render stage's too. Already-cached scenes cost a digest lookup.

**One thread, one composition at a time.** A preview request answers on its
own thread and composes alongside the warmer rather than behind it; the
warmer only ever takes one of
:data:`~etsy_listings.core.preparation.scenes.MAX_CONCURRENT_RENDERS`. A
preview of a scene the warmer is composing waits on the scene cache's
per-identity lock and reads the warmer's entry, so nothing is composed twice.

**The latest save wins.** Listings are queued by name, oldest first, and a
name already queued keeps its place. A listing saved again while it is being
warmed stops after the scene in hand and goes back on the queue, so the
next pass reads the listing as it now stands.

A scene that cannot be composed -- a template not prepared, a photo or design
missing, a listing that no longer loads -- is skipped: the preview endpoint
reports the same refusal when the seller opens it.
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from collections.abc import Callable

from etsy_listings.core.application.listing_reads import scene_artwork
from etsy_listings.core.application.mockup_templates import PreviewScene
from etsy_listings.core.application.prepared_previews import photo_warp_preview, saved_scene
from etsy_listings.core.config.listing import TemplateMediaEntry
from etsy_listings.core.errors import UserFacingError
from etsy_listings.core.render import load_design, load_template_base
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
    """Every template entry in ``name``'s saved ``media:``, in gallery order."""
    listing = workspace.load_listing(name)
    return [
        (entry.template, entry.colour)
        for entry in listing.media
        if isinstance(entry, TemplateMediaEntry)
    ]


def warm_scene(workspace: Workspace, name: str, template: str, colour: str | None) -> None:
    """Compose one of ``name``'s scenes at full size into the scene cache,
    or find it there. Refusals are the preview endpoint's."""
    scene = saved_scene(workspace, template, colour=colour, design=scene_artwork(workspace, name))
    if isinstance(scene, PreviewScene):
        photo_warp_preview(workspace, scene, base=load_template_base, design=load_design)


class SceneWarmer:
    """The worker thread and its queue of listing names; see the module."""

    def __init__(
        self,
        workspace: Workspace,
        *,
        scenes: Callable[[Workspace, str], list[Scene]] = gallery_scenes,
        warm: Callable[[Workspace, str, str, str | None], None] = warm_scene,
    ) -> None:
        self._workspace = workspace
        self._scenes = scenes
        self._warm = warm
        self._wake = threading.Condition()
        self._queued: OrderedDict[str, None] = OrderedDict()
        self._stopping = False
        self._idle = threading.Event()
        self._idle.set()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="scene-warmer", daemon=True)
        self._thread.start()

    def stop(self, *, timeout: float = 10.0) -> None:
        """Start nothing more; the scene in hand finishes or is abandoned
        with the daemon thread when it outlasts ``timeout``."""
        with self._wake:
            self._stopping = True
            self._queued.clear()
            self._wake.notify_all()
        if self._thread is not None:
            self._thread.join(timeout=timeout)

    def request(self, name: str) -> None:
        """Warm ``name``'s gallery as it is saved now."""
        with self._wake:
            if self._stopping:
                return
            self._queued.setdefault(name)
            self._idle.clear()
            self._wake.notify_all()

    def wait_idle(self, *, timeout: float) -> bool:
        """Block until every request so far is warmed. What a test waits on
        instead of a sleep; ``False`` on timeout."""
        return self._idle.wait(timeout)

    def _loop(self) -> None:
        while True:
            with self._wake:
                self._wake.wait_for(lambda: bool(self._queued) or self._stopping)
                if self._stopping:
                    self._idle.set()
                    return
                name, _ = self._queued.popitem(last=False)
            try:
                self._warm_listing(name)
            except Exception:
                logger.exception("warming listing %r's scenes failed", name)
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

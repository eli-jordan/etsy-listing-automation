"""Compose a prepared scene: the one path from accepted maps to pixels (ADR-0054).

The render stage's plan and apply, and every authoring or listing preview,
lease a scene here. Reading the saved inputs, acquiring the generation for the
target photo and naming the result's identity happen in one place, so the
identity a plan records is the identity apply and a preview compute.
"""

import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass

from PIL import Image

from etsy_listings.core.preparation.artifacts import (
    Artifacts,
    Manifest,
    PreparationInputs,
    StalePreparation,
)
from etsy_listings.core.preparation.scene_cache import SceneCache, photo_digest
from etsy_listings.core.render.config import MarigoldAppearance
from etsy_listings.core.render.identity import artwork_identity, prepared_scene_identity
from etsy_listings.core.render.io import MARIGOLD_PNG_COMPRESSION, encode_png
from etsy_listings.core.render.material import MaterialLayer, MaterialMaps, render_marigold_scene
from etsy_listings.core.render.types import RGB, RGBA
from etsy_listings.core.workspace import Workspace

MAX_CONCURRENT_RENDERS = 4
"""Compositions that may run at once, across previews and the render stage.

One peaks at about 1 GB for a 2048px photo, and the server answers each
preview request on its own thread: a page of full-size scenes arriving
together used to compose them all at once and exhaust memory. The rest
queue here, so four running together peak near 4 GB."""

_RENDER_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_RENDERS)


@dataclass(frozen=True)
class PreparedLayer:
    """One painted placement, in paint order."""

    artwork: RGBA
    placement_id: str | None = None


@dataclass(frozen=True)
class PreparedScene:
    """A scene whose generation stays leased until its ``lease_scene`` exits."""

    inputs: PreparationInputs
    """The saved pixel-affecting inputs the generation was acquired for."""
    manifest: Manifest
    identity: str
    """:func:`prepared_scene_identity` of exactly what :meth:`render` composes."""
    base: RGB
    layers: tuple[PreparedLayer, ...]
    appearance: MarigoldAppearance
    maps: Mapping[str | None, MaterialMaps]

    def render(self) -> Image.Image:
        with _RENDER_SLOTS:
            return render_marigold_scene(
                self.base,
                [
                    MaterialLayer(layer.artwork, self.maps[layer.placement_id], layer.placement_id)
                    for layer in self.layers
                ],
                appearance=self.appearance,
            )

    def encoded(self, cache: SceneCache) -> bytes:
        """The scene's PNG: ``cache``'s entry for :attr:`identity`, or a
        fresh composition, stored there before it is returned."""
        return cache.get_or_compose(
            self.identity,
            lambda: encode_png(self.render(), compression=MARIGOLD_PNG_COMPRESSION),
        )


@contextmanager
def lease_scene(
    workspace: Workspace,
    template: str,
    *,
    base: RGB,
    layers: Sequence[PreparedLayer],
    appearance: MarigoldAppearance,
    expected: PreparationInputs | None = None,
) -> Iterator[PreparedScene]:
    """Lease ``template``'s accepted generation to composite ``layers`` on ``base``.

    The saved inputs are read and the generation acquired under one short
    template lock, then the lock is released while the lease keeps the
    generation alive for composition. ``expected`` is inputs read earlier (a
    plan, or a preview before it decoded its images); saved inputs that have
    since changed refuse with :class:`StalePreparation`. Every refusal is an
    :class:`~etsy_listings.core.preparation.artifacts.ArtifactError`.
    """
    artifacts = Artifacts(workspace)
    with ExitStack() as lease:
        with artifacts.calibration.lock(template):
            inputs = artifacts.saved_inputs(template)
            if expected is not None and inputs.identity() != expected.identity():
                raise StalePreparation("Prepared maps are out of date; save and prepare again")
            acquired = lease.enter_context(
                artifacts.acquire(template, inputs, target_size=(base.shape[1], base.shape[0]))
            )
        identity = prepared_scene_identity(
            map_content=acquired.manifest.content_digest,
            placement_ids=[layer.placement_id for layer in layers],
            artwork_digests=[artwork_identity(layer.artwork) for layer in layers],
            photo_pixels=photo_digest(base),
            appearance=appearance,
        )
        yield PreparedScene(
            inputs, acquired.manifest, identity, base, tuple(layers), appearance, acquired.maps
        )

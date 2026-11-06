"""Compose a prepared scene: the one path from accepted maps to pixels (ADR-0054).

The render stage's plan and apply, and every authoring or listing preview,
lease a scene here. Reading the saved inputs, acquiring the generation for the
target photo and naming the result's identity happen in one place, so the
identity a plan records is the identity apply and a preview compute.
"""

import threading
from collections.abc import Iterator, Mapping, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, field

from PIL import Image

from etsy_listings.core.bounded_cache import BoundedCache
from etsy_listings.core.preparation.artifacts import (
    Artifacts,
    Manifest,
    PreparationInputs,
    StalePreparationError,
)
from etsy_listings.core.preparation.position_fits import (
    PositionFits,
    positioned_quads,
    scene_map_content,
)
from etsy_listings.core.preparation.scene_cache import SceneCache, photo_digest
from etsy_listings.core.render.config import LayerBoxes, MarigoldAppearance
from etsy_listings.core.render.identity import artwork_identity, prepared_scene_identity
from etsy_listings.core.render.io import MARIGOLD_PNG_COMPRESSION, encode_png
from etsy_listings.core.render.material import (
    MaterialLayer,
    MaterialMaps,
    prepare_material_artwork,
    render_marigold_scene,
)
from etsy_listings.core.render.types import RGB, RGBA, FloatMap
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.template_state import template_state

MAX_CONCURRENT_RENDERS = 4
"""Compositions that may run at once, across previews and the render stage.

One peaks at about 1 GB for a 2048px photo, and the server answers each
preview request on its own thread: a page of full-size scenes arriving
together used to compose them all at once and exhaust memory. The rest
queue here, so four running together peak near 4 GB."""

_RENDER_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_RENDERS)

PREMULTIPLIED_ARTWORK_BYTES = 768 * 1024**2
"""Budget for designs' premultiplied linear samples, kept by artwork digest.

Every colour of a scene, and every scene of a listing, composes the same
design, and preparing its samples was about 0.7 seconds of each. One
4200x4800 design's samples are 320 MB, so this keeps the two designs of a
light/dark listing."""

_PREMULTIPLIED: BoundedCache[str, FloatMap] = BoundedCache(
    PREMULTIPLIED_ARTWORK_BYTES, size=lambda samples: samples.nbytes
)


def _premultiplied(artwork: RGBA, digest: str) -> FloatMap:
    def prepare() -> FloatMap:
        samples = prepare_material_artwork(artwork)
        samples.flags.writeable = False  # shared by every composition reading it
        return samples

    return _PREMULTIPLIED.get_or_compute(digest, prepare)


@dataclass(frozen=True)
class PreparedLayer:
    """One painted placement, in paint order."""

    artwork: RGBA
    placement_id: str | None = None
    digest: str | None = None
    """``artwork_identity(artwork)`` when the caller already computed it;
    :func:`lease_scene` computes it otherwise."""


@dataclass(frozen=True)
class PreparedScene:
    """A scene whose generation stays leased until its ``lease_scene`` exits."""

    inputs: PreparationInputs
    """The saved pixel-affecting inputs the generation was acquired for."""
    manifest: Manifest
    map_content: str
    """The generation's content digest, combined with each position fit's
    when a layer is positioned (:func:`scene_map_content`)."""
    identity: str
    """:func:`prepared_scene_identity` of exactly what :meth:`render` composes."""
    base: RGB
    layers: tuple[PreparedLayer, ...]
    appearance: MarigoldAppearance
    maps: Mapping[str | None, MaterialMaps]
    digests: tuple[str, ...]
    """Each layer's ``artwork_identity``, in layer order."""

    def render(self) -> Image.Image:
        with _RENDER_SLOTS:
            return render_marigold_scene(
                self.base,
                [
                    MaterialLayer(
                        layer.artwork,
                        self.maps[layer.placement_id],
                        layer.placement_id,
                        premultiplied=_premultiplied(layer.artwork, digest),
                    )
                    for layer, digest in zip(self.layers, self.digests, strict=True)
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


@dataclass(frozen=True)
class Composition:
    """What a scene composites: artwork ``layers`` on the ``base`` photo, in
    ``appearance``."""

    base: RGB
    layers: Sequence[PreparedLayer]
    appearance: MarigoldAppearance
    photo_pixels: str | None = None
    """``photo_digest(base)`` when the caller already computed it."""
    boxes: LayerBoxes = field(default_factory=dict)
    """The listing's saved position for this template (ADR-0058). A layer it
    moves renders with its own position fit, never the template's maps."""


@contextmanager
def lease_scene(
    workspace: Workspace,
    template: str,
    composition: Composition,
    *,
    expected: PreparationInputs | None = None,
) -> Iterator[PreparedScene]:
    """Lease ``template``'s accepted generation to composite ``composition``.

    The saved inputs are read and the generation acquired under one short
    template lock, then the lock is released while the lease keeps the
    generation alive for composition. ``expected`` is inputs read earlier (a
    plan, or a preview before it decoded its images); saved inputs that have
    since changed refuse with :class:`StalePreparationError`. Every refusal is an
    :class:`~etsy_listings.core.preparation.artifacts.ArtifactError`.

    A layer ``composition.boxes`` positions is drawn with its position fit,
    fitted first -- or awaited, when another caller is fitting it -- and never
    with the template's maps (spec *Rendering -> Marigold (option B)*).
    """
    base, layers, appearance = composition.base, composition.layers, composition.appearance
    artifacts = Artifacts(workspace)
    fits = PositionFits(workspace)
    with ExitStack() as lease:
        with artifacts.calibration.lock(template):
            inputs = artifacts.saved_inputs(template)
            if expected is not None and inputs.identity() != expected.identity():
                raise StalePreparationError("Prepared maps are out of date; save and prepare again")
            acquired = lease.enter_context(
                artifacts.acquire(template, inputs, target_size=(base.shape[1], base.shape[0]))
            )
            config = template_state(workspace, template).require()
            requests = fits.requests(template, inputs, positioned_quads(config, composition.boxes))
        lease.enter_context(fits.lease(request.key for request in requests.values()))
        positioned = {key: fits.ensure(request) for key, request in requests.items()}
        maps = {**acquired.maps, **{key: fit.maps for key, fit in positioned.items()}}
        map_content = scene_map_content(acquired.manifest.content_digest, positioned)
        digests = tuple(
            layer.digest if layer.digest is not None else artwork_identity(layer.artwork)
            for layer in layers
        )
        identity = prepared_scene_identity(
            map_content=map_content,
            placement_ids=[layer.placement_id for layer in layers],
            artwork_digests=list(digests),
            photo_pixels=composition.photo_pixels or photo_digest(base),
            appearance=appearance,
        )
        yield PreparedScene(
            inputs=inputs,
            manifest=acquired.manifest,
            map_content=map_content,
            identity=identity,
            base=base,
            layers=tuple(layers),
            appearance=appearance,
            maps=maps,
            digests=digests,
        )

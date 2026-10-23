"""Previews of a template's *saved* scene, whichever renderer it uses.

:func:`saved_scene` is the one entry point for the listing editors and the
listing-template editor: it picks the renderer, so a route never has to. A
prepared scene composes through :func:`~etsy_listings.core.preparation.scenes.lease_scene`,
the render stage's own path, so a preview's identity is the rendered file's.

A full-size scene of either renderer is kept in
:class:`~etsy_listings.core.preparation.scene_cache.SceneCache`. Viewing it
again finds it there without decoding the photo or a design, when
:data:`~etsy_listings.core.preparation.scene_cache.PIXEL_DIGESTS` still knows
every file's pixels.
"""

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from etsy_listings.core.application.mockup_templates import (
    LayerDesign,
    PreviewScene,
    compose_preview,
    read_config,
    require_template,
    saved_preview,
)
from etsy_listings.core.application.refusals import (
    TemplatePhotoMissing,
    TemplatePreviewKindMismatch,
)
from etsy_listings.core.preparation.artifacts import ArtifactError, Artifacts, PreparationInputs
from etsy_listings.core.preparation.readiness import template_readiness
from etsy_listings.core.preparation.scene_cache import PIXEL_DIGESTS, SceneCache
from etsy_listings.core.preparation.scenes import PreparedLayer, lease_scene
from etsy_listings.core.render import (
    AnyTemplate,
    ColourMatrixTemplate,
    MarigoldAppearance,
    MarigoldRenderer,
    MultipleTemplate,
    PreparationRequired,
    encode_png,
    scene_colours,
)
from etsy_listings.core.render.identity import (
    PHOTO_WARP_PNG_COMPRESSION,
    photo_warp_scene_identity,
    prepared_scene_identity,
)
from etsy_listings.core.render.maps import DerivedMapCache
from etsy_listings.core.render.types import RGB, RGBA
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.calibration import CalibrationStore


@dataclass(frozen=True)
class PreparedPreview:
    png: bytes
    """The composed scene, encoded as the render stage writes it."""
    render_identity: str
    generation_id: str
    config_revision: str


def saved_scene(
    workspace: Workspace, name: str, *, colour: str | None, design: LayerDesign
) -> PreviewScene | PreparedPreview:
    """``name``'s saved scene with ``design`` asked once per layer, as
    :func:`~etsy_listings.core.application.mockup_templates.saved_preview`
    asks it. Photo warp returns the scene for the host to composite from its
    image memo; Marigold returns the composed image. Refusals:
    :class:`TemplateMissing`, :class:`TemplateConfigMissing`,
    :class:`TemplatePhotoMissing`, :class:`PreparationRequired`."""
    if isinstance(read_config(workspace, name).config.renderer, MarigoldRenderer):
        return prepared_preview(workspace, name, config=None, colour=colour, design=design)
    return saved_preview(workspace, name, colour=colour, design=design)


@dataclass(frozen=True)
class PhotoWarpPreview:
    png: bytes
    """The full-size scene, encoded as the render stage writes it."""
    render_identity: str


def photo_warp_preview(
    workspace: Workspace,
    scene: PreviewScene,
    *,
    base: Callable[[Path], RGB],
    design: Callable[[Path], RGBA],
) -> PhotoWarpPreview:
    """``scene`` at full size, from the cache when every file's pixel digest
    is still known, else composed from ``base`` and ``design`` (a host's
    decode memo) and stored. The composition uses the very arrays its
    identity was computed from."""
    painted = [
        (cfg, path)
        for cfg, path in zip(scene.layers, scene.designs, strict=True)
        if path is not None
    ]
    cache = SceneCache(workspace)
    photo_pixels = PIXEL_DIGESTS.photo(scene.photo.path)
    known = [digest for _, path in painted if (digest := PIXEL_DIGESTS.design(path)) is not None]
    if photo_pixels is not None and len(known) == len(painted):
        identity = photo_warp_scene_identity(
            photo_pixels=photo_pixels,
            layers=[(cfg, digest) for (cfg, _), digest in zip(painted, known, strict=True)],
        )
        png = cache.read(identity)
        if png is not None:
            return PhotoWarpPreview(png, identity)

    photo, photo_pixels = PIXEL_DIGESTS.decode_photo(scene.photo.path, base)
    decoded: dict[Path, tuple[RGBA, str]] = {}
    for _, path in painted:
        if path not in decoded:
            decoded[path] = PIXEL_DIGESTS.decode_design(path, design)
    identity = photo_warp_scene_identity(
        photo_pixels=photo_pixels, layers=[(cfg, decoded[path][1]) for cfg, path in painted]
    )

    def compose() -> bytes:
        maps = DerivedMapCache(scene.derived_dir)
        image = compose_preview(
            scene,
            base=photo,
            scale=1.0,
            design=lambda path: decoded[path][0],
            height=lambda: maps.height(scene.photo.map_key, photo),
            luminance=lambda: maps.luminance(scene.photo.map_key, photo),
        )
        return encode_png(image, compression=PHOTO_WARP_PNG_COMPRESSION)

    return PhotoWarpPreview(cache.get_or_compose(identity, compose), identity)


def prepared_preview(
    workspace: Workspace,
    name: str,
    *,
    config: AnyTemplate | None,
    colour: str | None,
    design: LayerDesign,
) -> PreparedPreview:
    """A Marigold scene at ``config``'s geometry (the saved one when
    ``None``), which must match the saved, prepared inputs. ``design`` is
    asked once per layer with the colour it depicts; a layer with no file is
    left bare."""
    require_template(workspace, name)
    store = CalibrationStore(workspace)
    artifacts = Artifacts(workspace)
    # Capture saved geometry/masks/reference and the selected target once;
    # lease_scene re-checks them after the images are decoded.
    with store.lock(name):
        saved = store.read(name)
        requested = config if config is not None else saved.config
        if requested.kind != saved.config.kind:
            raise TemplatePreviewKindMismatch(saved.config.kind)
        if not isinstance(requested.renderer, MarigoldRenderer) or not isinstance(
            saved.config.renderer, MarigoldRenderer
        ):
            raise PreparationRequired("Save the Marigold renderer selection before rendering")
        readiness = template_readiness(workspace, name, saved.config)
        if not readiness.can_render:
            raise PreparationRequired(readiness.message or "Prepare the template first")
        inputs = artifacts.saved_inputs(name)
        boxes = (
            {p.id: p.bounding_box for p in requested.placements}
            if isinstance(requested, MultipleTemplate)
            else {None: requested.bounding_box}
        )
        expected = {p.id: p.quad for p in inputs.placements}
        if {
            key: tuple((p.x, p.y) for p in box) for key, box in boxes.items()
        } != expected or requested.renderer.config.inference != inputs.inference:
            raise PreparationRequired(
                "Save geometry and inference settings, then rebuild or prepare the template"
            )
        depicted = colour if isinstance(requested, ColourMatrixTemplate) else None
        path = workspace.scene_photo(name, depicted).path
        if not path.is_file():
            raise TemplatePhotoMissing("Selected target photo is missing")
        sources = _layer_sources(requested, depicted, design)
        appearance = requested.renderer.config.appearance
        cache = SceneCache(workspace)
        try:
            cached = _cached(workspace, name, inputs, cache, path, sources, appearance)
        except ArtifactError as exc:
            raise PreparationRequired(str(exc)) from exc
        if cached is not None:
            png, identity, generation_id = cached
            return PreparedPreview(png, identity, generation_id, saved.revision)
        base, _ = PIXEL_DIGESTS.decode_photo(path)
        layers = _layers(sources)
    try:
        with lease_scene(
            workspace, name, base=base, layers=layers, appearance=appearance, expected=inputs
        ) as scene:
            return PreparedPreview(
                scene.encoded(cache), scene.identity, scene.manifest.generation_id, saved.revision
            )
    except ArtifactError as exc:
        raise PreparationRequired(str(exc)) from exc


def _cached(
    workspace: Workspace,
    name: str,
    inputs: PreparationInputs,
    cache: SceneCache,
    photo: Path,
    sources: list[tuple[Path, str | None]],
    appearance: MarigoldAppearance,
) -> tuple[bytes, str, str] | None:
    """The cached scene, without decoding, when every file's pixel digest is
    still known: ``(png, identity, generation_id)``, else ``None``. The
    identity is the one :func:`lease_scene` would compute from the decoded
    pixels, so an entry found under it is exactly that composition."""
    photo_pixels = PIXEL_DIGESTS.photo(photo)
    artwork = [PIXEL_DIGESTS.design(path) for path, _ in sources]
    if photo_pixels is None or None in artwork:
        return None
    manifest = Artifacts(workspace).inspect(name, inputs)
    identity = prepared_scene_identity(
        map_content=manifest.content_digest,
        placement_ids=[placement for _, placement in sources],
        artwork_digests=[digest for digest in artwork if digest is not None],
        photo_pixels=photo_pixels,
        appearance=appearance,
    )
    png = cache.read(identity)
    return None if png is None else (png, identity, manifest.generation_id)


def _layer_sources(
    config: AnyTemplate, colour: str | None, design: LayerDesign
) -> list[tuple[Path, str | None]]:
    """``(design file, placement id)`` per printed layer, in paint order. A
    layer with no file is left bare."""
    sources = []
    for depicted, placement in scene_colours(config, colour):
        path = design(depicted)
        if path is not None:
            sources.append((path, placement))
    return sources


def _layers(sources: list[tuple[Path, str | None]]) -> list[PreparedLayer]:
    decoded: dict[Path, RGBA] = {}
    layers = []
    for path, placement in sources:
        if path not in decoded:
            decoded[path], _ = PIXEL_DIGESTS.decode_design(path)
        layers.append(PreparedLayer(decoded[path], placement))
    return layers

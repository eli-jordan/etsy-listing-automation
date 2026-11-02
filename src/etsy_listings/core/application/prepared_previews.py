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

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

from etsy_listings.core.application.mockup_templates import (
    LayerDesign,
    LazyMaps,
    PreviewScene,
    compose_preview,
    read_config,
    require_template,
    saved_preview,
)
from etsy_listings.core.application.refusals import (
    TemplatePhotoMissingError,
    TemplatePreviewKindMismatchError,
)
from etsy_listings.core.preparation.artifacts import ArtifactError, Artifacts, PreparationInputs
from etsy_listings.core.preparation.position_fits import (
    FitRequest,
    PositionFits,
    positioned_quads,
    scene_map_content,
)
from etsy_listings.core.preparation.readiness import template_readiness
from etsy_listings.core.preparation.scene_cache import PIXEL_DIGESTS, SceneCache
from etsy_listings.core.preparation.scenes import Composition, PreparedLayer, lease_scene
from etsy_listings.core.render import (
    AnyTemplate,
    ColourMatrixTemplate,
    LayerBoxes,
    MarigoldAppearance,
    MarigoldRenderer,
    MultipleTemplate,
    PreparationRequiredError,
    RenderConfig,
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
    workspace: Workspace,
    name: str,
    *,
    colour: str | None,
    design: LayerDesign,
    boxes: LayerBoxes | None = None,
) -> PreviewScene | PreparedPreview:
    """``name``'s saved scene with ``design`` asked once per layer, as
    :func:`~etsy_listings.core.application.mockup_templates.saved_preview`
    asks it. Photo warp returns the scene for the host to composite from its
    image memo; Marigold returns the composed image. Either renders at the
    listing's ``boxes`` where it holds a position -- Marigold with a fit of
    each posed quad, waiting for one being fitted (option B). Refusals:
    :class:`TemplateMissingError`, :class:`TemplateConfigMissingError`,
    :class:`TemplatePhotoMissingError`, :class:`PreparationRequiredError`."""
    if isinstance(read_config(workspace, name).config.renderer, MarigoldRenderer):
        return _prepared_preview(workspace, name, None, _Layers(colour, design, boxes or {}))
    return saved_preview(workspace, name, colour=colour, design=design, boxes=boxes)


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
    cached = _cached_photo_warp(cache, scene, painted)
    if cached is not None:
        return cached

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
            maps=LazyMaps(
                height=lambda: maps.height(scene.photo.map_key, photo),
                luminance=lambda: maps.luminance(scene.photo.map_key, photo),
            ),
        )
        return encode_png(image, compression=PHOTO_WARP_PNG_COMPRESSION)

    return PhotoWarpPreview(cache.get_or_compose(identity, compose), identity)


def _cached_photo_warp(
    cache: SceneCache, scene: PreviewScene, painted: list[tuple[RenderConfig, Path]]
) -> PhotoWarpPreview | None:
    """The cached scene, without decoding, when every file's pixel digest is
    still known."""
    photo_pixels = PIXEL_DIGESTS.photo(scene.photo.path)
    known = [digest for _, path in painted if (digest := PIXEL_DIGESTS.design(path)) is not None]
    if photo_pixels is None or len(known) != len(painted):
        return None
    identity = photo_warp_scene_identity(
        photo_pixels=photo_pixels,
        layers=[(cfg, digest) for (cfg, _), digest in zip(painted, known, strict=True)],
    )
    png = cache.read(identity)
    return None if png is None else PhotoWarpPreview(png, identity)


def _requested_marigold(
    saved: AnyTemplate, config: AnyTemplate | None
) -> tuple[AnyTemplate, MarigoldRenderer]:
    """The geometry to render (the saved one when ``config`` is None) and its
    renderer; refuses a different kind or a renderer not saved as Marigold."""
    requested = config if config is not None else saved
    if requested.kind != saved.kind:
        raise TemplatePreviewKindMismatchError(saved.kind)
    if not isinstance(requested.renderer, MarigoldRenderer) or not isinstance(
        saved.renderer, MarigoldRenderer
    ):
        raise PreparationRequiredError("Save the Marigold renderer selection before rendering")
    return requested, requested.renderer


def _check_prepared_geometry(
    requested: AnyTemplate, renderer: MarigoldRenderer, inputs: PreparationInputs
) -> None:
    boxes = (
        {p.id: p.bounding_box for p in requested.placements}
        if isinstance(requested, MultipleTemplate)
        else {None: requested.bounding_box}
    )
    expected = {p.id: p.quad for p in inputs.placements}
    if {
        key: tuple((p.x, p.y) for p in box) for key, box in boxes.items()
    } != expected or renderer.config.inference != inputs.inference:
        raise PreparationRequiredError(
            "Save geometry and inference settings, then rebuild or prepare the template"
        )


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
    return _prepared_preview(workspace, name, config, _Layers(colour, design, {}))


@dataclass(frozen=True)
class _Layers:
    """What a scene paints: the colour it depicts, each layer's design, and
    the listing's saved position (ADR-0058). A layer ``boxes`` positions shows
    its position fit, never the template's maps (option B)."""

    colour: str | None
    design: LayerDesign
    boxes: LayerBoxes


def _prepared_preview(
    workspace: Workspace, name: str, config: AnyTemplate | None, painted: _Layers
) -> PreparedPreview:
    colour, design, boxes = painted.colour, painted.design, painted.boxes
    require_template(workspace, name)
    store = CalibrationStore(workspace)
    artifacts = Artifacts(workspace)
    # Capture saved geometry/masks/reference and the selected target once;
    # lease_scene re-checks them after the images are decoded.
    with store.lock(name):
        saved = store.read(name)
        requested, renderer = _requested_marigold(saved.config, config)
        readiness = template_readiness(workspace, name, saved.config)
        if not readiness.can_render:
            raise PreparationRequiredError(readiness.message or "Prepare the template first")
        inputs = artifacts.saved_inputs(name)
        _check_prepared_geometry(requested, renderer, inputs)
        depicted = colour if isinstance(requested, ColourMatrixTemplate) else None
        path = workspace.scene_photo(name, depicted).path
        if not path.is_file():
            raise TemplatePhotoMissingError("Selected target photo is missing")
        sources = _layer_sources(requested, depicted, design)
        appearance = renderer.config.appearance
        cache = SceneCache(workspace)
        try:
            fits = PositionFits(workspace).requests(
                name, inputs, positioned_quads(saved.config, boxes)
            )
            cached = _cached(
                workspace, name, inputs, cache, _SceneFiles(path, sources, appearance, fits)
            )
        except ArtifactError as exc:
            raise PreparationRequiredError(str(exc)) from exc
        if cached is not None:
            png, identity, generation_id = cached
            return PreparedPreview(png, identity, generation_id, saved.revision)
        base, _ = PIXEL_DIGESTS.decode_photo(path)
        layers = _layers(sources)
    try:
        with lease_scene(
            workspace, name, Composition(base, layers, appearance, boxes), expected=inputs
        ) as scene:
            return PreparedPreview(
                scene.encoded(cache), scene.identity, scene.manifest.generation_id, saved.revision
            )
    except ArtifactError as exc:
        raise PreparationRequiredError(str(exc)) from exc


@dataclass(frozen=True)
class _SceneFiles:
    """A composition named by its files, before any is decoded: the photo,
    each layer's design and placement, and the appearance."""

    photo: Path
    sources: list[tuple[Path, str | None]]
    appearance: MarigoldAppearance
    fits: Mapping[str | None, FitRequest]
    """The positioned layers' fits; a scene whose fit is not stored yet is
    not looked up, but leased, which fits it."""


def _cached(
    workspace: Workspace,
    name: str,
    inputs: PreparationInputs,
    cache: SceneCache,
    files: _SceneFiles,
) -> tuple[bytes, str, str] | None:
    """The cached scene, without decoding, when every file's pixel digest is
    still known: ``(png, identity, generation_id)``, else ``None``. The
    identity is the one :func:`lease_scene` would compute from the decoded
    pixels, so an entry found under it is exactly that composition."""
    sources = files.sources
    photo_pixels = PIXEL_DIGESTS.photo(files.photo)
    artwork = [PIXEL_DIGESTS.design(path) for path, _ in sources]
    if photo_pixels is None or None in artwork:
        return None
    stored = PositionFits(workspace)
    fits = {key: stored.read(request) for key, request in files.fits.items()}
    if None in fits.values():
        return None
    manifest = Artifacts(workspace).inspect(name, inputs)
    identity = prepared_scene_identity(
        map_content=scene_map_content(
            manifest.content_digest, {k: v for k, v in fits.items() if v is not None}
        ),
        placement_ids=[placement for _, placement in sources],
        artwork_digests=[digest for digest in artwork if digest is not None],
        photo_pixels=photo_pixels,
        appearance=files.appearance,
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

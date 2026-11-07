"""Give me this scene at this size: the one question every picture of a mockup
template asks, for either renderer, saved or drawn.

:func:`saved_scene` answers it for what is on disk and :func:`draft_scene` for
the geometry under the seller's cursor. Each picks the renderer, composes, and
answers with a finished picture, so a host only encodes and serves it. A
:class:`RenderedScene` is the PNG the render stage writes, with the identity
that names it; a :class:`SceneFrame` is a transient editor-size image with no
identity, which the host encodes as it likes. A prepared scene composes through
:func:`~etsy_listings.core.preparation.scenes.lease_scene`, the render stage's
own path, so a preview's identity is the rendered file's. Whether a draft still
matches what is saved, and what a failure to use prepared files means, are
answered here too: a refusal arrives as ``PreparationRequiredError``.

A full-size scene of either renderer is kept in
:class:`~etsy_listings.core.preparation.scene_cache.SceneCache`. Viewing it
again finds it there without decoding the photo or a design, when
:data:`~etsy_listings.core.preparation.scene_cache.PIXEL_DIGESTS` still knows
every file's pixels.

Decoding is the one thing a caller supplies, as :class:`SceneImages`: the
server's memo between the frames of a drag (``server/api/imagecache.py``, which
is request-serving state and stays there) or :data:`DISK_IMAGES`, for a caller
with no memo. Marigold's full-size scenes always decode through
``PIXEL_DIGESTS``, as the render stage's do.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from PIL import Image

from etsy_listings.core.application.mockup_templates import (
    LayerDesign,
    LazyMaps,
    PreviewGeometry,
    PreviewScene,
    compose_preview,
    require_template,
    saved_preview,
    unsaved_preview,
)
from etsy_listings.core.application.preparation.previews import (
    EditorDraft,
    check_prepared_geometry,
    editor_preview,
    prepared_renderer,
)
from etsy_listings.core.application.refusals import TemplatePhotoMissingError
from etsy_listings.core.preparation.artifacts import ArtifactError, Artifacts, PreparationInputs
from etsy_listings.core.preparation.position_fits import (
    FitRequest,
    PositionFits,
    positioned_quads,
    scene_map_content,
)
from etsy_listings.core.preparation.predictions import PredictionError
from etsy_listings.core.preparation.readiness import template_readiness
from etsy_listings.core.preparation.scene_cache import PIXEL_DIGESTS, SceneCache
from etsy_listings.core.preparation.scenes import Composition, PreparedLayer, lease_scene
from etsy_listings.core.render import (
    AnyTemplate,
    ColourMatrixTemplate,
    LayerBoxes,
    MarigoldAppearance,
    MarigoldRenderer,
    PreparationRequiredError,
    RenderConfig,
    encode_png,
    load_design,
    load_template_base,
    load_template_config,
    prepare_material_artwork,
    scene_colours,
)
from etsy_listings.core.render.identity import (
    PHOTO_WARP_PNG_COMPRESSION,
    photo_warp_scene_identity,
    prepared_scene_identity,
)
from etsy_listings.core.render.maps import DerivedMapCache
from etsy_listings.core.render.types import RGB, RGBA, FloatMap
from etsy_listings.core.workspace import Workspace
from etsy_listings.core.workspace.calibration import CalibrationStore, MaskEdit

SceneSize = Literal["editor", "full"]
"""How big a picture to answer. ``full`` is the photo's own resolution, what
``apply`` writes; ``editor`` is whatever the decoder's canvas makes of it, for
a canvas being dragged against. A Marigold scene already saved has one size."""


@dataclass(frozen=True)
class RenderedScene:
    """A finished full-size picture and what names it."""

    png: bytes
    """The composed scene, encoded as the render stage writes it."""
    render_identity: str
    generation_id: str | None = None
    """The map generation a prepared scene was composed from, for promotion."""
    config_revision: str | None = None
    """The calibration revision a prepared scene was composed against."""


@dataclass(frozen=True)
class SceneFrame:
    """A disposable editor-size image: never cached, so it has no identity."""

    image: Image.Image
    interactive: bool = False
    """A Marigold draft's approximate composite, not the render it predicts."""


ScenePicture = RenderedScene | SceneFrame


@dataclass(frozen=True)
class EditorCanvas:
    """What a Photo warp frame composites over: the photo as the decoder sized
    it, that size as a fraction of the true one, and its derived maps."""

    base: RGB
    scale: float
    maps: LazyMaps


class SceneImages(Protocol):
    """How a scene's files become arrays. A fake needs no files at all."""

    def photo(self, path: Path) -> RGB:
        """The whole photo at its true size."""
        ...

    def design(self, path: Path) -> RGBA:
        """A design file, whole."""
        ...

    def canvas(self, scene: PreviewScene) -> EditorCanvas:
        """``scene``'s photo as an editor frame draws on it."""
        ...

    def artwork(self, path: Path) -> tuple[RGBA, FloatMap]:
        """A design as a Marigold editor frame prints it, with its linear samples."""
        ...


class _DiskImages:
    """Each file read as it is asked for, at full size: nothing is remembered,
    and an editor frame is simply not downscaled."""

    def photo(self, path: Path) -> RGB:
        return load_template_base(path)

    def design(self, path: Path) -> RGBA:
        return load_design(path)

    def canvas(self, scene: PreviewScene) -> EditorCanvas:
        base = load_template_base(scene.photo.path)
        maps = DerivedMapCache(scene.derived_dir)
        key = scene.photo.map_key
        return EditorCanvas(
            base,
            1.0,
            LazyMaps(
                height=lambda: maps.height(key, base), luminance=lambda: maps.luminance(key, base)
            ),
        )

    def artwork(self, path: Path) -> tuple[RGBA, FloatMap]:
        design = load_design(path)
        return design, prepare_material_artwork(design)


DISK_IMAGES: SceneImages = _DiskImages()


@dataclass(frozen=True)
class SceneLayers:
    """What a saved scene paints: the colour it depicts, each layer's design,
    and the listing's saved position (ADR-0058). A layer ``boxes`` positions
    shows its position fit, never the template's maps (option B)."""

    colour: str | None
    design: LayerDesign
    boxes: LayerBoxes = field(default_factory=dict)


@dataclass(frozen=True)
class SceneDraft:
    """The calibrator's unsaved scene. ``geometry`` is what a Photo warp frame
    needs, and ``document`` the whole template as drawn, which a Marigold one
    parses: a drag may pass through a shape no ``template.yaml`` could hold,
    and Photo warp has never had to refuse it. ``revision`` is the calibration
    it was drawn against, ``mask_edits`` the strokes not yet saved, and
    ``design`` resolves the one file every layer shows, and may refuse."""

    geometry: PreviewGeometry
    document: Mapping[str, object]
    revision: str
    mask_edits: list[MaskEdit]
    design: Callable[[], Path]


def saved_scene(
    workspace: Workspace,
    name: str,
    layers: SceneLayers,
    *,
    size: SceneSize,
    images: SceneImages,
) -> ScenePicture:
    """``name``'s saved scene with ``layers.design`` asked once per layer, as
    :func:`~etsy_listings.core.application.mockup_templates.saved_preview`
    asks it. Either renderer renders at the listing's ``boxes`` where it holds
    a position -- Marigold with a fit of each posed quad, waiting for one being
    fitted (option B). Refusals: :class:`TemplateMissingError`, the template
    state's own, :class:`TemplatePhotoMissingError`,
    :class:`PreparationRequiredError`."""
    require_template(workspace, name)
    config = CalibrationStore(workspace).state(name).require()
    if isinstance(config.renderer, MarigoldRenderer):
        return _prepared_preview(workspace, name, None, layers)
    scene = saved_preview(
        workspace, name, colour=layers.colour, design=layers.design, boxes=layers.boxes
    )
    return _photo_warp(workspace, scene, size, images)


def draft_scene(
    workspace: Workspace,
    name: str,
    draft: SceneDraft,
    *,
    size: SceneSize,
    images: SceneImages,
) -> ScenePicture:
    """``draft`` composited at ``size``. A Photo warp draft renders whatever it
    draws. A Marigold one must still be drawn against the saved calibration,
    and at full size must match the prepared inputs, with no unsaved strokes."""
    if not isinstance(draft.geometry.renderer, MarigoldRenderer):
        scene = unsaved_preview(workspace, name, draft.geometry, design=draft.design)
        return _photo_warp(workspace, scene, size, images)
    config = load_template_config(dict(draft.document))
    if size == "editor":
        return _editor_frame(workspace, name, draft, config, images)
    if draft.mask_edits:
        raise PreparationRequiredError("Save draft mask edits before full preview")
    layers = SceneLayers(draft.geometry.colour, lambda _colour: draft.design())
    return _prepared_preview(workspace, name, config, layers)


def _editor_frame(
    workspace: Workspace, name: str, draft: SceneDraft, config: AnyTemplate, images: SceneImages
) -> SceneFrame:
    """The interactive composite of an unsaved draft: never cached, and
    refused rather than prepared when its maps are not ready."""
    try:
        image = editor_preview(
            workspace,
            name,
            EditorDraft(config, draft.revision, draft.mask_edits, draft.geometry.colour),
            base=images.photo,
            artwork=lambda: images.artwork(draft.design()),
        )
    except (ArtifactError, PredictionError, OSError) as exc:
        # Prepared maps or evidence on disk that cannot be used: not a refusal
        # of the request, but the same answer as preparation being needed.
        raise PreparationRequiredError(str(exc)) from exc
    return SceneFrame(image, interactive=True)


def _photo_warp(
    workspace: Workspace, scene: PreviewScene, size: SceneSize, images: SceneImages
) -> ScenePicture:
    if size == "full":
        return _full_photo_warp(workspace, scene, images)
    canvas = images.canvas(scene)
    return SceneFrame(
        compose_preview(
            scene, base=canvas.base, scale=canvas.scale, design=images.design, maps=canvas.maps
        )
    )


def _full_photo_warp(
    workspace: Workspace, scene: PreviewScene, images: SceneImages
) -> RenderedScene:
    """``scene`` at full size, from the cache when every file's pixel digest
    is still known, else composed from ``images`` and stored. The composition
    uses the very arrays its identity was computed from."""
    painted = [
        (cfg, path)
        for cfg, path in zip(scene.layers, scene.designs, strict=True)
        if path is not None
    ]
    cache = SceneCache(workspace)
    cached = _cached_photo_warp(cache, scene, painted)
    if cached is not None:
        return cached

    photo, photo_pixels = PIXEL_DIGESTS.decode_photo(scene.photo.path, images.photo)
    decoded: dict[Path, tuple[RGBA, str]] = {}
    for _, path in painted:
        if path not in decoded:
            decoded[path] = PIXEL_DIGESTS.decode_design(path, images.design)
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

    return RenderedScene(cache.get_or_compose(identity, compose), identity)


def _cached_photo_warp(
    cache: SceneCache, scene: PreviewScene, painted: list[tuple[RenderConfig, Path]]
) -> RenderedScene | None:
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
    return None if png is None else RenderedScene(png, identity)


def _prepared_preview(
    workspace: Workspace, name: str, config: AnyTemplate | None, painted: SceneLayers
) -> RenderedScene:
    colour, design, boxes = painted.colour, painted.design, painted.boxes
    require_template(workspace, name)
    store = CalibrationStore(workspace)
    artifacts = Artifacts(workspace)
    # Capture saved geometry/masks/reference and the selected target once;
    # lease_scene re-checks them after the images are decoded.
    with store.lock(name):
        saved = store.read(name)
        requested = config if config is not None else saved.config
        renderer = prepared_renderer(saved.config, requested)
        readiness = template_readiness(workspace, name, saved.config)
        if not readiness.can_render:
            raise PreparationRequiredError(readiness.message or "Prepare the template first")
        inputs = artifacts.saved_inputs(name)
        check_prepared_geometry(requested, renderer, inputs)
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
            return RenderedScene(png, identity, generation_id, saved.revision)
        base, photo_pixels = PIXEL_DIGESTS.decode_photo(path)
        layers = _layers(sources)
    try:
        with lease_scene(
            workspace,
            name,
            Composition(base, layers, appearance, photo_pixels=photo_pixels, boxes=boxes),
            expected=inputs,
        ) as scene:
            return RenderedScene(
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
    """Each layer's decoded design with the digest the decode already
    named it by, so composing does not hash it again."""
    decoded: dict[Path, tuple[RGBA, str]] = {}
    layers = []
    for path, placement in sources:
        if path not in decoded:
            decoded[path] = PIXEL_DIGESTS.decode_design(path)
        artwork, digest = decoded[path]
        layers.append(PreparedLayer(artwork, placement, digest))
    return layers

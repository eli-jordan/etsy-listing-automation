from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
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
from etsy_listings.core.application.preparation.draft_rules import (
    EditorDraft,
    check_prepared_geometry,
    prepared_renderer,
)
from etsy_listings.core.application.preparation.previews import editor_preview
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
from etsy_listings.core.preparation.scene_cache import (
    PIXEL_DIGESTS,
    RememberedDigests,
    SceneCache,
)
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
    png: bytes
    """The composed scene, encoded as the render stage writes it."""
    render_identity: str
    generation_id: str | None = None
    """Kept for promotion."""
    config_revision: str | None = None
    remembered: bool = False
    """Found under a digest from :class:`RememberedDigests`, not one this
    process computed: likely right, but not yet checked."""


@dataclass(frozen=True)
class SceneFrame:
    image: Image.Image
    interactive: bool = False
    """A Marigold draft's approximate composite, not the render it predicts."""


ScenePicture = RenderedScene | SceneFrame


@dataclass(frozen=True)
class EditorCanvas:
    """``scale`` is the decoded size as a fraction of the photo's true size."""

    base: RGB
    scale: float
    maps: LazyMaps


class SceneImages(Protocol):
    def photo(self, path: Path) -> RGB: ...

    def design(self, path: Path) -> RGBA: ...

    def canvas(self, scene: PreviewScene) -> EditorCanvas: ...

    def artwork(self, path: Path) -> tuple[RGBA, FloatMap]:
        """A design as a Marigold editor frame prints it, with its linear samples."""
        ...


class _DiskImages:
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
    colour: str | None
    design: LayerDesign
    boxes: LayerBoxes = field(default_factory=dict)


@dataclass(frozen=True)
class SceneDraft:
    """``document`` is the whole template as drawn: a drag may pass through
    a shape no ``template.yaml`` could hold, which only Marigold refuses."""

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
    return _saved_scene(workspace, name, layers, _Asked(size, images, remembered=False))


def remembered_scene(
    workspace: Workspace, name: str, layers: SceneLayers, *, images: SceneImages
) -> ScenePicture:
    """May answer from digests kept from before a restart, so only a viewer
    that checks with :func:`remembered_scene_was_wrong` asks; nothing that
    renders or deploys does."""
    return _saved_scene(workspace, name, layers, _Asked("full", images, remembered=True))


def remembered_scene_was_wrong(
    workspace: Workspace, name: str, layers: SceneLayers, *, images: SceneImages
) -> bool:
    """Computing the true scene also corrects the remembered digests, so a
    wrong answer is given once."""
    shown = remembered_scene(workspace, name, layers, images=images)
    if not isinstance(shown, RenderedScene) or not shown.remembered:
        return False
    actual = saved_scene(workspace, name, layers, size="full", images=images)
    return isinstance(actual, RenderedScene) and actual.render_identity != shown.render_identity


@dataclass(frozen=True)
class _Asked:
    size: SceneSize
    images: SceneImages
    remembered: bool


def _saved_scene(
    workspace: Workspace, name: str, layers: SceneLayers, asked: _Asked
) -> ScenePicture:
    require_template(workspace, name)
    config = CalibrationStore(workspace).state(name).require()
    if isinstance(config.renderer, MarigoldRenderer):
        return _prepared_preview(workspace, name, None, layers, remembered=asked.remembered)
    scene = saved_preview(
        workspace, name, colour=layers.colour, design=layers.design, boxes=layers.boxes
    )
    return _photo_warp(workspace, scene, asked.size, asked.images, remembered=asked.remembered)


def layer_artwork(
    workspace: Workspace, name: str, layers: SceneLayers, placement: str | None
) -> Path | None:
    require_template(workspace, name)
    config = CalibrationStore(workspace).state(name).require()
    for depicted, layer in scene_colours(config, layers.colour):
        if layer == placement:
            return layers.design(depicted)
    return None


def draft_scene(
    workspace: Workspace,
    name: str,
    draft: SceneDraft,
    *,
    size: SceneSize,
    images: SceneImages,
) -> ScenePicture:
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
    with _unusable_files_need_preparation(ArtifactError, PredictionError, OSError):
        image = editor_preview(
            workspace,
            name,
            EditorDraft(config, draft.revision, draft.mask_edits, draft.geometry.colour),
            base=images.photo,
            artwork=lambda: images.artwork(draft.design()),
        )
    return SceneFrame(image, interactive=True)


def _photo_warp(
    workspace: Workspace,
    scene: PreviewScene,
    size: SceneSize,
    images: SceneImages,
    *,
    remembered: bool = False,
) -> ScenePicture:
    if size == "full":
        return _full_photo_warp(workspace, scene, images, remembered=remembered)
    canvas = images.canvas(scene)
    return SceneFrame(
        compose_preview(
            scene, base=canvas.base, scale=canvas.scale, design=images.design, maps=canvas.maps
        )
    )


@dataclass
class _Recall:
    """A digest this process computed, else one :class:`RememberedDigests`
    kept; ``used`` says whether any came from the latter."""

    remembered: RememberedDigests | None
    used: bool = False

    def photo(self, path: Path) -> str | None:
        return self._recall("photo", path, PIXEL_DIGESTS.photo(path))

    def design(self, path: Path) -> str | None:
        return self._recall("design", path, PIXEL_DIGESTS.design(path))

    def _recall(self, kind: str, path: Path, computed: str | None) -> str | None:
        if computed is not None or self.remembered is None:
            return computed
        digest = self.remembered.recall(kind, path)
        self.used = self.used or digest is not None
        return digest


def _remember(workspace: Workspace, photo: Path, designs: list[Path]) -> None:
    """For the next restart's first view."""
    store = RememberedDigests(workspace)
    store.remember("photo", photo)
    for path in designs:
        store.remember("design", path)


def _full_photo_warp(
    workspace: Workspace, scene: PreviewScene, images: SceneImages, *, remembered: bool
) -> RenderedScene:
    """Composes from the very arrays its identity was computed from."""
    painted = [
        (cfg, path)
        for cfg, path in zip(scene.layers, scene.designs, strict=True)
        if path is not None
    ]
    cache = SceneCache(workspace)
    recall = _Recall(RememberedDigests(workspace) if remembered else None)
    cached = _cached_photo_warp(cache, scene, painted, recall)
    if cached is not None:
        return cached

    photo, photo_pixels = PIXEL_DIGESTS.decode_photo(scene.photo.path, images.photo)
    decoded: dict[Path, tuple[RGBA, str]] = {}
    for _, path in painted:
        if path not in decoded:
            decoded[path] = PIXEL_DIGESTS.decode_design(path, images.design)
    _remember(workspace, scene.photo.path, list(decoded))
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
    cache: SceneCache,
    scene: PreviewScene,
    painted: list[tuple[RenderConfig, Path]],
    recall: _Recall,
) -> RenderedScene | None:
    photo_pixels = recall.photo(scene.photo.path)
    known = [digest for _, path in painted if (digest := recall.design(path)) is not None]
    if photo_pixels is None or len(known) != len(painted):
        return None
    identity = photo_warp_scene_identity(
        photo_pixels=photo_pixels,
        layers=[(cfg, digest) for (cfg, _), digest in zip(painted, known, strict=True)],
    )
    png = cache.read(identity)
    return None if png is None else RenderedScene(png, identity, remembered=recall.used)


def _prepared_preview(
    workspace: Workspace,
    name: str,
    config: AnyTemplate | None,
    painted: SceneLayers,
    *,
    remembered: bool = False,
) -> RenderedScene:
    colour, design, boxes = painted.colour, painted.design, painted.boxes
    require_template(workspace, name)
    store = CalibrationStore(workspace)
    artifacts = Artifacts(workspace)
    # Captured once under the lock; lease_scene re-checks them after decoding.
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
        with _unusable_files_need_preparation(ArtifactError):
            fits = PositionFits(workspace).requests(
                name, inputs, positioned_quads(saved.config, boxes)
            )
            recall = _Recall(RememberedDigests(workspace) if remembered else None)
            cached = _cached(
                workspace, name, inputs, _SceneFiles(path, sources, appearance, fits), recall
            )
        if cached is not None:
            png, identity, generation_id = cached
            return RenderedScene(
                png, identity, generation_id, saved.revision, remembered=recall.used
            )
        base, photo_pixels = PIXEL_DIGESTS.decode_photo(path)
        layers = _layers(sources)
        _remember(workspace, path, [source for source, _ in sources])
    with (
        _unusable_files_need_preparation(ArtifactError),
        lease_scene(
            workspace,
            name,
            Composition(base, layers, appearance, photo_pixels=photo_pixels, boxes=boxes),
            expected=inputs,
        ) as scene,
    ):
        return RenderedScene(
            scene.encoded(cache), scene.identity, scene.manifest.generation_id, saved.revision
        )


@contextmanager
def _unusable_files_need_preparation(*unusable: type[Exception]) -> Iterator[None]:
    """Prepared maps or evidence on disk that cannot be used are not a refusal
    of the request, but the same answer as preparation being needed."""
    try:
        yield
    except unusable as exc:
        raise PreparationRequiredError(str(exc)) from exc


@dataclass(frozen=True)
class _SceneFiles:
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
    files: _SceneFiles,
    recall: _Recall,
) -> tuple[bytes, str, str] | None:
    """``(png, identity, generation_id)``; the identity is the one :func:`lease_scene` computes."""
    sources = files.sources
    photo_pixels = recall.photo(files.photo)
    artwork = [recall.design(path) for path, _ in sources]
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
    png = SceneCache(workspace).read(identity)
    return None if png is None else (png, identity, manifest.generation_id)


def _layer_sources(
    config: AnyTemplate, colour: str | None, design: LayerDesign
) -> list[tuple[Path, str | None]]:
    sources = []
    for depicted, placement in scene_colours(config, colour):
        path = design(depicted)
        if path is not None:
            sources.append((path, placement))
    return sources


def _layers(sources: list[tuple[Path, str | None]]) -> list[PreparedLayer]:
    decoded: dict[Path, tuple[RGBA, str]] = {}
    layers = []
    for path, placement in sources:
        if path not in decoded:
            decoded[path] = PIXEL_DIGESTS.decode_design(path)
        artwork, digest = decoded[path]
        layers.append(PreparedLayer(artwork, placement, digest))
    return layers

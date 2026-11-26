"""The calibrator's mockup template operations: overviews, kinds, colour
reports, saved calibration and previews.

Every path comes from ``Workspace``, whose accessors keep a template name that
arrived in a URL inside the root."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import yaml
from PIL import Image

from etsy_listings.core.application.refusals import (
    TemplateAlreadyCalibratedError,
    TemplateKindRefusedError,
    TemplateMissingError,
    TemplatePhotoMissingError,
    TemplatePreviewKindMismatchError,
)
from etsy_listings.core.config.slug import slug_map
from etsy_listings.core.render.config import (
    AnyRenderer,
    AnyTemplate,
    BoundingBox,
    ColourMatrixTemplate,
    DisplaceConfig,
    LayerBoxes,
    MultipleTemplate,
    PhotoWarpRenderer,
    Point,
    PreparationRequiredError,
    RenderConfig,
    ShadeConfig,
    SingleTemplate,
    scene_layers,
)
from etsy_listings.core.render.pipeline import Layer, render_scene
from etsy_listings.core.render.swatch import sample_swatch
from etsy_listings.core.render.types import RGB, RGBA, FloatMap
from etsy_listings.core.workspace.calibration import CalibrationStore, MaskEdit
from etsy_listings.core.workspace.listing_documents import ListingDocuments, ListingMissingError
from etsy_listings.core.workspace.template_state import (
    TemplateAbsent,
    TemplateLoaded,
    TemplateNeedsRepair,
    TemplateState,
)
from etsy_listings.core.workspace.workspace import (
    AmbiguousColourSuffixError,
    ScenePhoto,
    Workspace,
)

TemplateKind = Literal["colour-matrix", "multiple", "single"]


@dataclass(frozen=True)
class TemplatePhoto:
    colour: str | None
    file: str


@dataclass(frozen=True)
class TemplateOverview:
    name: str
    kind: TemplateKind | None
    colours: list[str]
    photos: list[TemplatePhoto]
    has_config: bool
    status_reason: str | None
    """Why it is not calibrated yet, in the rail's words; ``None`` once it is."""
    width: int | None
    height: int | None
    """The photo's **true** pixel size: the space ``template.yaml``'s boxes
    are in, which the editor's downscaled canvas cannot tell the client."""
    labels: list[str]
    config: AnyTemplate | None = None
    """What was read to make this row, or ``None`` for one that did not load."""

    @property
    def calibrated(self) -> bool:
        return self.status_reason is None


def require_template(workspace: Workspace, name: str) -> None:
    if not workspace.has_template(name):
        raise TemplateMissingError(name)


def list_templates(workspace: Workspace) -> list[TemplateOverview]:
    return [
        _overview(workspace, name) for name in workspace.template_names(include_uncalibrated=True)
    ]


def _overview(workspace: Workspace, name: str) -> TemplateOverview:
    state = CalibrationStore(workspace).state(name)
    width, height = _photo_size(_stand_in_photo(workspace, name, state))
    if not isinstance(state, TemplateLoaded):
        return TemplateOverview(
            name=name,
            kind=None,
            colours=[],
            photos=[],
            has_config=not isinstance(state, TemplateAbsent),
            status_reason=_not_loaded_reason(state),
            width=width,
            height=height,
            labels=[],
        )
    config = state.config
    return TemplateOverview(
        name=name,
        kind=config.kind,
        colours=_colours(workspace, name, config),
        photos=_photos(workspace, name, config),
        has_config=True,
        status_reason=_status_reason(config),
        width=width,
        height=height,
        labels=config.labels,
        config=config,
    )


def _colours(workspace: Workspace, name: str, config: AnyTemplate) -> list[str]:
    if isinstance(config, ColourMatrixTemplate):
        return workspace.template_colours(name)
    if isinstance(config, MultipleTemplate):
        return [p.colour for p in config.placements]
    return [config.colour] if config.colour is not None else []


def _not_loaded_reason(state: TemplateState) -> str | None:
    if isinstance(state, TemplateAbsent):
        return "no kind set"
    if isinstance(state, TemplateNeedsRepair):
        return f"needs repair: {state.reason}"
    return state.reason


def _stand_in_photo(workspace: Workspace, name: str, state: TemplateState) -> Path | None:
    if state.config is None:
        return workspace.template_preview_photo(name)
    try:
        return workspace.template_main_photo(name, state.config)
    except FileNotFoundError:
        return workspace.template_preview_photo(name)


def _photo_size(photo: Path | None) -> tuple[int | None, int | None]:
    """Header only: ``Image.open`` is lazy."""
    if photo is None:
        return None, None
    try:
        with Image.open(photo) as image:
            width, height = image.size
    except OSError:
        return None, None
    return int(width), int(height)


def _status_reason(config: AnyTemplate) -> str | None:
    if not isinstance(config, MultipleTemplate):
        return None
    if not config.placements:
        return "no boxes"
    uncoloured = sum(1 for p in config.placements if not p.colour.strip())
    if uncoloured:
        noun, verb = ("box", "has") if uncoloured == 1 else ("boxes", "have")
        return f"{uncoloured} {noun} {verb} no colour"
    return None


def _photos(workspace: Workspace, name: str, config: AnyTemplate) -> list[TemplatePhoto]:
    if not isinstance(config, ColourMatrixTemplate):
        scene = workspace.template_scene_image(name)
        return [TemplatePhoto(colour=None, file=workspace.relative_path(scene))]
    photos: list[TemplatePhoto] = []
    for colour in workspace.template_colours(name):
        try:
            path = workspace.scene_photo(name, colour).path
        except AmbiguousColourSuffixError:
            continue
        photos.append(TemplatePhoto(colour=colour, file=workspace.relative_path(path)))
    return photos


def template_photo(workspace: Workspace, name: str, colour: str | None) -> Path:
    require_template(workspace, name)
    source: Path | None
    if colour is None:
        source = _stand_in_photo(workspace, name, CalibrationStore(workspace).state(name))
    else:
        try:
            source = workspace.template_base_image(name, colour)
        except AmbiguousColourSuffixError:
            source = None
    if source is None or not source.is_file():
        wanted = f"{name!r}" if colour is None else f"{name!r} colour {colour!r}"
        raise TemplatePhotoMissingError(f"no photo for {wanted}")
    return source


@dataclass(frozen=True)
class ColourAssignment:
    """What one photo of a candidate ``colour-matrix`` set will be taken as.
    ``clean`` is false when assigning the kind will rename it (ADR-0004: the
    filename *is* the slugified colour)."""

    filename: str
    colour: str
    clean: bool


def colour_report(workspace: Workspace, name: str) -> list[ColourAssignment]:
    require_template(workspace, name)
    photos = workspace.template_photos(name)
    slugs = _colour_slugs(workspace, photos)
    return [
        ColourAssignment(filename=photo.name, colour=slugs[photo], clean=slugs[photo] == photo.stem)
        for photo in photos
    ]


def assign_kind(workspace: Workspace, name: str, kind: TemplateKind) -> AnyTemplate:
    require_template(workspace, name)
    state = CalibrationStore(workspace).state(name)
    if not isinstance(state, TemplateAbsent):
        state.require()
        raise TemplateAlreadyCalibratedError(name)
    photos = workspace.template_photos(name)
    if not photos:
        raise TemplateKindRefusedError(f"no photos in {name!r}")

    config: AnyTemplate
    if kind == "colour-matrix":
        photos = _rename_photos_to_slugs(workspace, photos)
        with Image.open(photos[0]) as img:
            size = img.size
        config = ColourMatrixTemplate(
            renderer=PhotoWarpRenderer(type="photo-warp"), bounding_box=_default_box(size)
        )
    else:
        if len(photos) != 1:
            raise TemplateKindRefusedError(f"{kind} kind expects one photo, found {len(photos)}")
        scene = workspace.template_scene_image(name)
        photos[0].replace(scene)
        with Image.open(scene) as img:
            size = img.size
        config = (
            MultipleTemplate(renderer=PhotoWarpRenderer(type="photo-warp"), placements=[])
            if kind == "multiple"
            else SingleTemplate(
                renderer=PhotoWarpRenderer(type="photo-warp"), bounding_box=_default_box(size)
            )
        )
    CalibrationStore(workspace).write_config(name, config)
    return config


def _default_box(size: tuple[int, int]) -> BoundingBox:
    w, h = size
    return (
        Point(x=w * 0.2, y=h * 0.2),
        Point(x=w * 0.8, y=h * 0.2),
        Point(x=w * 0.8, y=h * 0.8),
        Point(x=w * 0.2, y=h * 0.8),
    )


def _colour_slugs(workspace: Workspace, photos: list[Path]) -> dict[Path, str]:
    slugs = slug_map([photo.stem for photo in photos], workspace.load_exceptions())
    return {photo: slugs[photo.stem] for photo in photos}


def _rename_photos_to_slugs(workspace: Workspace, photos: list[Path]) -> list[Path]:
    """Via a temporary name: on a case-insensitive filesystem a case-only
    ``replace()`` is a no-op."""
    slugs = _colour_slugs(workspace, photos)
    renamed: list[Path] = []
    for photo in photos:
        target = photo.with_name(f"{slugs[photo]}.png")
        # By name: WindowsPath equality ignores case, so it would skip a case-only rename.
        if photo.name == target.name:
            renamed.append(photo)
            continue
        staging = photo.with_name(f".{slugs[photo]}.renaming.png")
        photo.replace(staging)
        staging.replace(target)
        renamed.append(target)
    return sorted(renamed)


@dataclass(frozen=True)
class SavedConfig:
    config: AnyTemplate
    modified_at: datetime
    revision: str


def read_config(workspace: Workspace, name: str) -> SavedConfig:
    require_template(workspace, name)
    store = CalibrationStore(workspace)
    with store.lock(name):
        saved = store.read(name)
        modified_at = datetime.fromtimestamp(
            workspace.template_config_file(name).stat().st_mtime, tz=UTC
        )
        return SavedConfig(config=saved.config, modified_at=modified_at, revision=saved.revision)


def save_config(workspace: Workspace, name: str, config: AnyTemplate) -> None:
    require_template(workspace, name)
    CalibrationStore(workspace).write_config(name, config)


@dataclass(frozen=True)
class CalibrationSave:
    config: AnyTemplate
    expected_revision: str
    request_id: str
    mask_edits: list[MaskEdit] | None = None


@dataclass(frozen=True)
class SavedCalibration:
    """A retry of a labels-only save changes nothing and answers False, as any
    save with no change does."""

    config: AnyTemplate
    revision: str
    labels_only: bool


def _without_labels(config: AnyTemplate) -> AnyTemplate:
    return config.model_copy(update={"labels": []})


def _only_labels_differ(before: AnyTemplate, after: AnyTemplate) -> bool:
    return before.labels != after.labels and _without_labels(before) == _without_labels(after)


def save_calibration(workspace: Workspace, name: str, save: CalibrationSave) -> SavedCalibration:
    """ADR-0054: configuration and flattened masks commit as one revision."""
    require_template(workspace, name)
    store = CalibrationStore(workspace)
    with store.lock(name):
        before = store.read(name).config
        if before.kind != save.config.kind:
            raise TemplateKindRefusedError("Template kind cannot be changed after calibration")
        saved = store.save(
            name,
            save.config,
            expected_revision=save.expected_revision,
            request_id=save.request_id,
            mask_edits=save.mask_edits,
        )
    return SavedCalibration(
        saved.config,
        saved.revision,
        labels_only=not save.mask_edits and _only_labels_differ(before, saved.config),
    )


@dataclass(frozen=True)
class PositionedListing:
    listing: str
    placements: tuple[str, ...]


def positioned_listings(workspace: Workspace, template: str) -> list[PositionedListing]:
    require_template(workspace, template)
    documents = ListingDocuments(workspace)
    found: list[PositionedListing] = []
    for name in workspace.listing_names():
        try:
            document = documents.read(name)
        except (ListingMissingError, yaml.YAMLError, UnicodeDecodeError):
            continue
        placements = _held_position(document, template)
        if placements is not None:
            found.append(PositionedListing(name, placements))
    return found


def _held_position(document: dict[str, object], template: str) -> tuple[str, ...] | None:
    positions = document.get("template_positions")
    if document.get("lifecycle") == "deleted" or not isinstance(positions, dict):
        return None
    entry = positions.get(template)
    if not isinstance(entry, dict):
        return None
    placements = entry.get("placements")
    if isinstance(placements, dict) and placements:
        return tuple(sorted(str(p) for p in placements))
    return () if "bounding_box" in entry else None


def _load_config(workspace: Workspace, name: str) -> AnyTemplate:
    require_template(workspace, name)
    return CalibrationStore(workspace).state(name).require()


@dataclass(frozen=True)
class PreviewGeometry:
    kind: TemplateKind
    boxes: tuple[BoundingBox, ...]
    colour: str | None = None
    renderer: AnyRenderer | None = None
    displace: DisplaceConfig = field(default_factory=DisplaceConfig)
    shade: ShadeConfig = field(default_factory=ShadeConfig)


@dataclass(frozen=True)
class PreviewScene:
    """Layers are in the photo's true pixel space."""

    photo: ScenePhoto
    derived_dir: Path
    layers: tuple[RenderConfig, ...]
    designs: tuple[Path | None, ...]
    """The design file each layer composites, as the caller resolved it --
    parallel to ``layers``. ``None`` leaves that layer's garment bare."""


LayerDesign = Callable[[str | None], Path | None]
"""``depicted colour -> design file`` for one layer of a saved scene, or
``None`` to leave the layer bare. The colour is the one
:func:`~etsy_listings.core.render.config.scene_layers` says the layer
depicts, so a ``multiple`` scene can print a different file per placement
(A35)."""


def _drawn_or_saved_renderer(geometry: PreviewGeometry, config: AnyTemplate) -> AnyRenderer:
    return geometry.renderer or config.renderer


def unsaved_preview(
    workspace: Workspace, name: str, geometry: PreviewGeometry, *, design: Callable[[], Path]
) -> PreviewScene:
    config = _load_config(workspace, name)
    if not isinstance(_drawn_or_saved_renderer(geometry, config), PhotoWarpRenderer):
        raise PreparationRequiredError("Prepare the template first: Marigold maps are required")
    kind = config.kind
    if geometry.kind != kind:
        raise TemplatePreviewKindMismatchError(kind)
    settings = (
        geometry.renderer.config if isinstance(geometry.renderer, PhotoWarpRenderer) else None
    )
    layers = tuple(
        RenderConfig(
            bounding_box=box,
            displace=settings.displace if settings else geometry.displace,
            shade=settings.shade if settings else geometry.shade,
        )
        for box in geometry.boxes
    )
    path = design()
    return _scene(workspace, name, geometry.colour, layers, tuple(path for _ in layers))


def saved_preview(
    workspace: Workspace,
    name: str,
    *,
    colour: str | None,
    design: LayerDesign,
    boxes: LayerBoxes | None = None,
) -> PreviewScene:
    config = _load_config(workspace, name)
    depicted = colour if isinstance(config, ColourMatrixTemplate) else None
    pairs = scene_layers(config, depicted, boxes or {})
    designs = tuple(design(layer_colour) for layer_colour, _ in pairs)
    return _scene(workspace, name, depicted, tuple(cfg for _, cfg in pairs), designs)


def _scene(
    workspace: Workspace,
    name: str,
    colour: str | None,
    layers: tuple[RenderConfig, ...],
    designs: tuple[Path | None, ...],
) -> PreviewScene:
    photo = workspace.scene_photo(name, colour)
    if not photo.path.is_file():
        missing = f"colour {colour!r}" if colour is not None else f"{name!r}"
        raise TemplatePhotoMissingError(f"no mockup photo for {missing}")
    return PreviewScene(
        photo=photo,
        derived_dir=workspace.template_derived_dir(name),
        layers=layers,
        designs=designs,
    )


@dataclass(frozen=True)
class LazyMaps:
    height: Callable[[], FloatMap]
    luminance: Callable[[], FloatMap]


def compose_preview(
    scene: PreviewScene,
    *,
    base: RGB,
    scale: float,
    design: Callable[[Path], RGBA],
    maps: LazyMaps,
) -> Image.Image:
    painted = [
        (scaled(cfg, scale), path)
        for cfg, path in zip(scene.layers, scene.designs, strict=True)
        if path is not None
    ]
    layers = [cfg for cfg, _ in painted]
    return render_scene(
        base,
        [Layer(design=design(path), cfg=cfg) for cfg, path in painted],
        height=maps.height() if any(cfg.displace.enabled for cfg in layers) else None,
        luminance=maps.luminance() if any(cfg.shade.enabled for cfg in layers) else None,
    )


def scaled(cfg: RenderConfig, scale: float) -> RenderConfig:
    """``displace.strength`` scales too: it multiplies an absolute pixel
    figure. ``model_copy`` skips revalidation, so a true-size box survives a
    tiny preview."""
    if scale == 1.0:
        return cfg
    return cfg.model_copy(
        update={
            "bounding_box": tuple(Point(x=p.x * scale, y=p.y * scale) for p in cfg.bounding_box),
            "displace": cfg.displace.model_copy(update={"strength": cfg.displace.strength * scale}),
        }
    )


def template_swatch(
    workspace: Workspace, name: str, colour: str, *, photo: Callable[[Path], RGB]
) -> str:
    config = _load_config(workspace, name)
    if not isinstance(config, ColourMatrixTemplate):
        raise TemplatePhotoMissingError(f"{name!r} is not a colour-matrix template")
    scene = workspace.scene_photo(name, colour)
    if not scene.path.is_file():
        raise TemplatePhotoMissingError(f"no photo for {name!r} colour {colour!r}")
    red, green, blue = sample_swatch(photo(scene.path), config.bounding_box)
    return f"#{red:02x}{green:02x}{blue:02x}"

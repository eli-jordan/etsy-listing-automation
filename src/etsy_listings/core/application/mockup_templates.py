"""Calibrating a mockup template: what the calibrator's rail lists, the kind
a folder of photos is given, ``template.yaml`` read and saved, and the scene
a preview composites (module-structure plan, PR 7).

Nothing here creates a template. A template is a folder of photos the
seller puts in the workspace, so every operation names one that exists and
refuses with :class:`~etsy_listings.core.application.refusals.TemplateMissing`
otherwise. Every path comes from ``Workspace``: template names arrive from
URLs, and its accessors are where "stays inside the root" is enforced
(ADR-0013, ADR-0046) -- an unusable name is its ``InvalidNameError``.

A template is exactly one of three kinds; its config shape and a preview's
geometry both follow which kind is in play.

Previews are the real renderer, not an approximation (architecture, *The
calibrator*): :func:`saved_preview` and :func:`unsaved_preview` say which
photo, which derived maps and which layers a preview composites, from the
saved ``template.yaml`` or from the unsaved geometry under the seller's
cursor; :func:`compose_preview` composites them through ``render_scene``.
The decoded images are the caller's to supply. The server holds a memo of
them between the frames of a drag (``server/api/imagecache.py``), which is
request-serving state and stays there; this module takes images and
geometry, and asks for a derived map only when a layer uses it.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from PIL import Image

from etsy_listings.core.application.refusals import (
    TemplateAlreadyCalibrated,
    TemplateConfigMissing,
    TemplateKindRefused,
    TemplateMissing,
    TemplatePhotoMissing,
    TemplatePreviewKindMismatch,
)
from etsy_listings.core.config.errors import ConfigLoadError
from etsy_listings.core.config.slug import slug_map
from etsy_listings.core.render.config import (
    AnyTemplate,
    BoundingBox,
    ColourMatrixTemplate,
    DisplaceConfig,
    MultipleTemplate,
    Point,
    RenderConfig,
    ShadeConfig,
    SingleTemplate,
)
from etsy_listings.core.render.pipeline import Layer, render_scene
from etsy_listings.core.render.swatch import sample_swatch
from etsy_listings.core.render.types import RGB, RGBA, FloatMap
from etsy_listings.core.workspace.workspace import (
    AmbiguousColourSuffixError,
    ScenePhoto,
    Workspace,
)

TemplateKind = Literal["colour-matrix", "multiple", "single"]


# ----------------------------------------------------------------- the rail


@dataclass(frozen=True)
class TemplatePhoto:
    """One scene photo: which colour it is (``None`` for a fixed scene) and
    where it really is, workspace-relative."""

    colour: str | None
    file: str


@dataclass(frozen=True)
class TemplateOverview:
    """One template as the calibrator's rail shows it. Calibration status is
    derived on every read, never stored -- a persisted flag could disagree
    with the config beside it."""

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

    @property
    def calibrated(self) -> bool:
        return self.status_reason is None


def require_template(workspace: Workspace, name: str) -> None:
    """Refuse a template that is not there: :class:`TemplateMissing`."""
    if not workspace.has_template(name):
        raise TemplateMissing(name)


def list_templates(workspace: Workspace) -> list[TemplateOverview]:
    """Every template, calibrated or not -- the calibrator is what writes
    ``template.yaml``, so the folders with none are the ones it is for."""
    return [
        _overview(workspace, name) for name in workspace.template_names(include_uncalibrated=True)
    ]


def _overview(workspace: Workspace, name: str) -> TemplateOverview:
    width, height = _photo_size(workspace, name)
    try:
        config = workspace.load_template_config(name)
    except ConfigLoadError:
        return TemplateOverview(
            name=name,
            kind=None,
            colours=[],
            photos=[],
            has_config=False,
            status_reason="no kind set",
            width=width,
            height=height,
        )
    if isinstance(config, ColourMatrixTemplate):
        colours = workspace.template_colours(name)
    elif isinstance(config, MultipleTemplate):
        colours = [p.colour for p in config.placements]
    else:
        colours = [config.colour] if config.colour is not None else []
    return TemplateOverview(
        name=name,
        kind=config.kind,
        colours=colours,
        photos=_photos(workspace, name, config),
        has_config=True,
        status_reason=_status_reason(config),
        width=width,
        height=height,
    )


def _photo_size(workspace: Workspace, name: str) -> tuple[int | None, int | None]:
    """From the image header alone (``Image.open`` is lazy). An unreadable
    file answers ``None``: listing a template is how the seller reaches the
    UI that fixes it."""
    photo = workspace.template_preview_photo(name)
    if photo is None:
        return None, None
    try:
        with Image.open(photo) as image:
            width, height = image.size
    except OSError:
        return None, None
    return int(width), int(height)


def _status_reason(config: AnyTemplate) -> str | None:
    """Only ``multiple`` has states beyond "has a config": a chart starts
    with no placements, and a box can be placed before anyone says which
    colour it depicts. The other kinds get a box when their kind is
    assigned -- a badly placed box is wrong, not incomplete."""
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
    """Asked of ``Workspace.scene_photo`` rather than composed from
    ADR-0004's convention, which cannot express its own trailing-segment
    fallback. An ambiguous colour is skipped rather than guessed at."""
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
    """The template's own photo: ``colour``'s in a colour-matrix set, else
    whichever stands for the template. :class:`TemplatePhotoMissing` when
    there is none, or the colour's suffix is ambiguous -- the case
    ``template_base_image`` refuses to guess at."""
    require_template(workspace, name)
    source: Path | None
    if colour is None:
        source = workspace.template_preview_photo(name)
    else:
        try:
            source = workspace.template_base_image(name, colour)
        except AmbiguousColourSuffixError:
            source = None
    if source is None or not source.is_file():
        wanted = f"{name!r}" if colour is None else f"{name!r} colour {colour!r}"
        raise TemplatePhotoMissing(f"no photo for {wanted}")
    return source


# ---------------------------------------------------------- kind and colours


@dataclass(frozen=True)
class ColourAssignment:
    """What one photo of a candidate ``colour-matrix`` set will be taken as.
    ``clean`` is false when assigning the kind will rename it (ADR-0004: the
    filename *is* the slugified colour)."""

    filename: str
    colour: str
    clean: bool


def colour_report(workspace: Workspace, name: str) -> list[ColourAssignment]:
    """Each photo's colour, before committing to ``colour-matrix``. Writes
    nothing; ``SlugCollisionError`` for two photos on one slug."""
    require_template(workspace, name)
    photos = workspace.template_photos(name)
    slugs = _colour_slugs(workspace, photos)
    return [
        ColourAssignment(filename=photo.name, colour=slugs[photo], clean=slugs[photo] == photo.stem)
        for photo in photos
    ]


def assign_kind(workspace: Workspace, name: str, kind: TemplateKind) -> AnyTemplate:
    """The first calibration step: say what the template is, and write its
    starting ``template.yaml``.

    ``colour-matrix`` renames each photo to the slug its name means, as the
    colour report said it would; a fixed-scene kind makes its one photo
    ``scene.png`` (ADR-0014). Refusals, nothing written: :class:`TemplateMissing`,
    :class:`TemplateAlreadyCalibrated`, :class:`TemplateKindRefused` (no
    photos, or a set for a fixed scene) and ``SlugCollisionError``.
    """
    require_template(workspace, name)
    if workspace.template_config_file(name).is_file():
        raise TemplateAlreadyCalibrated(name)
    photos = workspace.template_photos(name)
    if not photos:
        raise TemplateKindRefused(f"no photos in {name!r}")

    config: AnyTemplate
    if kind == "colour-matrix":
        # ADR-0004 makes the filename the slug, and this is where that becomes
        # true: `new` writes the slug into a listing's media, so a photo left
        # as `Heather Grey.png` fails to render from a template the calibrator
        # had declared finished.
        photos = _rename_photos_to_slugs(workspace, photos)
        with Image.open(photos[0]) as img:
            size = img.size
        config = ColourMatrixTemplate(bounding_box=_default_box(size))
    else:
        if len(photos) != 1:
            raise TemplateKindRefused(f"{kind} kind expects one photo, found {len(photos)}")
        scene = workspace.template_scene_image(name)
        photos[0].replace(scene)
        with Image.open(scene) as img:
            size = img.size
        config = (
            MultipleTemplate(placements=[])
            if kind == "multiple"
            else SingleTemplate(bounding_box=_default_box(size))
        )
    workspace.save_template_config(name, config)
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
    """Through ``slug_map`` with ``exceptions.yaml``, so the calibrator's
    slug is the rest of the tool's (ADR-0004). Two photos on one slug raise
    ``SlugCollisionError`` rather than one being lost at rename time."""
    slugs = slug_map([photo.stem for photo in photos], workspace.load_exceptions())
    return {photo: slugs[photo.stem] for photo in photos}


def _rename_photos_to_slugs(workspace: Workspace, photos: list[Path]) -> list[Path]:
    """Each photo renamed to ``{slug}.png``; the new paths, sorted.

    A case-only rename (``Forest.png`` -> ``forest.png``) goes via a
    temporary name: on a case-insensitive filesystem ``replace()`` onto a
    path differing only in case is a no-op, which would make the calibrator
    behave differently on the two platforms this tool runs on.
    """
    slugs = _colour_slugs(workspace, photos)
    renamed: list[Path] = []
    for photo in photos:
        target = photo.with_name(f"{slugs[photo]}.png")
        # By *name*: `WindowsPath("Forest.png") == WindowsPath("forest.png")`,
        # so a Path comparison would skip exactly the case-only rename.
        if photo.name == target.name:
            renamed.append(photo)
            continue
        staging = photo.with_name(f".{slugs[photo]}.renaming.png")
        photo.replace(staging)
        staging.replace(target)
        renamed.append(target)
    return sorted(renamed)


# --------------------------------------------------------------- the config


@dataclass(frozen=True)
class SavedConfig:
    config: AnyTemplate
    modified_at: datetime


def read_config(workspace: Workspace, name: str) -> SavedConfig:
    """The template's ``template.yaml`` and when it was last written.
    :class:`TemplateConfigMissing` for one with no config yet -- loaded
    before its file is stat()ed, so that is a refusal, not an ``OSError``."""
    config = _load_config(workspace, name)
    modified_at = datetime.fromtimestamp(
        workspace.template_config_file(name).stat().st_mtime, tz=UTC
    )
    return SavedConfig(config=config, modified_at=modified_at)


def save_config(workspace: Workspace, name: str, config: AnyTemplate) -> None:
    """Write ``config`` as the template's ``template.yaml``. The calibrator
    saves the whole document, whichever kind it is."""
    require_template(workspace, name)
    workspace.save_template_config(name, config)


def _load_config(workspace: Workspace, name: str) -> AnyTemplate:
    require_template(workspace, name)
    try:
        return workspace.load_template_config(name)
    except ConfigLoadError as exc:
        raise TemplateConfigMissing(name) from exc


# ---------------------------------------------------------------- previews


@dataclass(frozen=True)
class PreviewGeometry:
    """Unsaved geometry: what is under the seller's cursor, not what
    ``template.yaml`` says. ``kind`` is the shape it was given in; ``boxes``
    one per layer (a ``multiple`` chart's placements, else one); ``colour``
    the colour-matrix photo to composite over."""

    kind: TemplateKind
    boxes: tuple[BoundingBox, ...]
    colour: str | None = None
    displace: DisplaceConfig = field(default_factory=DisplaceConfig)
    shade: ShadeConfig = field(default_factory=ShadeConfig)


@dataclass(frozen=True)
class PreviewScene:
    """Everything a preview composites except the images themselves: which
    photo (and the key its derived maps cache under), where those maps live,
    and the layers in the photo's true pixel space."""

    photo: ScenePhoto
    derived_dir: Path
    layers: tuple[RenderConfig, ...]
    design: Path
    """The design file to composite, as the caller resolved it."""


def unsaved_preview(
    workspace: Workspace, name: str, geometry: PreviewGeometry, *, design: Callable[[], Path]
) -> PreviewScene:
    """The calibrator's live preview. Geometry shaped for another kind than
    the template is refuses with :class:`TemplatePreviewKindMismatch`.

    ``design`` resolves the file to composite -- a calibrator test design or
    a listing's artwork, whose libraries are the caller's -- and may refuse;
    it is asked after the kind check and before the photo is looked for.
    Refusals: :class:`TemplateMissing`, :class:`TemplateConfigMissing`,
    :class:`TemplatePhotoMissing`."""
    kind = _load_config(workspace, name).kind
    if geometry.kind != kind:
        raise TemplatePreviewKindMismatch(kind)
    layers = tuple(
        RenderConfig(bounding_box=box, displace=geometry.displace, shade=geometry.shade)
        for box in geometry.boxes
    )
    return _scene(workspace, name, geometry.colour, layers, design)


def saved_preview(
    workspace: Workspace, name: str, *, colour: str | None, design: Callable[[], Path]
) -> PreviewScene:
    """The saved geometry, as the render stage composites it -- the listing
    editors' read-only preview. ``colour`` picks the photo of a
    colour-matrix set and means nothing to the other kinds."""
    config = _load_config(workspace, name)
    layers: tuple[RenderConfig, ...]
    if isinstance(config, MultipleTemplate):
        layers = tuple(config.render_config_for(p) for p in config.placements)
    else:
        layers = (config.render_config(),)
    return _scene(
        workspace,
        name,
        colour if isinstance(config, ColourMatrixTemplate) else None,
        layers,
        design,
    )


def _scene(
    workspace: Workspace,
    name: str,
    colour: str | None,
    layers: tuple[RenderConfig, ...],
    design: Callable[[], Path],
) -> PreviewScene:
    # The design is resolved before the photo is looked for: an unknown design
    # was refused ahead of a missing photo before this moved out of the route.
    design_path = design()
    photo = workspace.scene_photo(name, colour)
    if not photo.path.is_file():
        missing = f"colour {colour!r}" if colour is not None else f"{name!r}"
        raise TemplatePhotoMissing(f"no mockup photo for {missing}")
    return PreviewScene(
        photo=photo,
        derived_dir=workspace.template_derived_dir(name),
        layers=layers,
        design=design_path,
    )


def compose_preview(
    scene: PreviewScene,
    *,
    base: RGB,
    scale: float,
    design: RGBA,
    height: Callable[[], FloatMap],
    luminance: Callable[[], FloatMap],
) -> Image.Image:
    """Composite ``design`` onto ``base`` -- the scene's photo, possibly
    downscaled by ``scale`` -- at the scene's layers, scaled to match.
    ``height`` and ``luminance`` supply the derived maps at ``base``'s size,
    and are asked only when a layer displaces or shades."""
    layers = [scaled(cfg, scale) for cfg in scene.layers]
    return render_scene(
        base,
        [Layer(design=design, cfg=cfg) for cfg in layers],
        height=height() if any(cfg.displace.enabled for cfg in layers) else None,
        luminance=luminance() if any(cfg.shade.enabled for cfg in layers) else None,
    )


def scaled(cfg: RenderConfig, scale: float) -> RenderConfig:
    """``cfg`` restated on a canvas ``scale`` times the photo's true size.

    Boxes are stored in the photo's true pixel space, so a downscaled base
    needs them scaled -- and ``displace.strength`` with them, since it is
    multiplied by an absolute pixel figure (``DISPLACE_MAX_PX``); left alone
    the editor would show several times the distortion of the render it
    predicts. ``shade`` is per-pixel. ``model_copy`` skips revalidation on
    purpose: a box valid at true size must not become degenerate because the
    preview is small.
    """
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
    """A colour-matrix colour's real garment shade, ``#rrggbb``: the median
    pixel inside the saved box of the colour's own photo, which ``photo``
    decodes. Only a colour-matrix template has a photo per colour to sample
    (:class:`TemplatePhotoMissing` otherwise, as for a colour with none)."""
    config = _load_config(workspace, name)
    if not isinstance(config, ColourMatrixTemplate):
        raise TemplatePhotoMissing(f"{name!r} is not a colour-matrix template")
    scene = workspace.scene_photo(name, colour)
    if not scene.path.is_file():
        raise TemplatePhotoMissing(f"no photo for {name!r} colour {colour!r}")
    red, green, blue = sample_swatch(photo(scene.path), config.bounding_box)
    return f"#{red:02x}{green:02x}{blue:02x}"

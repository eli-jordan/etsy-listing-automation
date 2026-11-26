from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace
from functools import partial
from pathlib import Path
from typing import Literal, override

from pydantic import BaseModel, ConfigDict

from etsy_listings.core.config.garment_profile import GarmentProfile
from etsy_listings.core.config.listing import Listing, TemplateMediaEntry
from etsy_listings.core.config.settings import SettingsProblem
from etsy_listings.core.config.template_positions import layer_boxes
from etsy_listings.core.engine.change import Action, Verdict
from etsy_listings.core.engine.context import RunContext, Swatch
from etsy_listings.core.engine.lock import (
    Lockfile,
    canonical_hash,
    hash_bytes,
    hash_file,
    to_workspace_relative_posix,
)
from etsy_listings.core.engine.stage import Blocked, Stage, StageApplyResult, StageBlockedError
from etsy_listings.core.engine.stages.gates import (
    check_artwork,
    check_garment_profile_chosen,
    check_prepared_maps,
    check_render_photo,
    check_render_template,
    check_scene_colour,
    check_template_positions,
    resolved_design,
)
from etsy_listings.core.preparation.artifacts import ArtifactError, PreparationInputs
from etsy_listings.core.preparation.readiness import template_readiness
from etsy_listings.core.preparation.scene_cache import SceneCache, photo_digest, write_atomic
from etsy_listings.core.preparation.scenes import Composition, PreparedLayer, lease_scene
from etsy_listings.core.render.config import (
    AnyTemplate,
    BoundingBox,
    LayerBoxes,
    MarigoldAppearance,
    PhotoWarpRenderer,
    RenderConfig,
    scene_boxes,
    scene_colours,
    scene_layers,
)
from etsy_listings.core.render.identity import (
    PHOTO_WARP_PNG_COMPRESSION,
    artwork_identity,
    photo_warp_scene_identity,
)
from etsy_listings.core.render.io import (
    encode_png,
    load_design,
    load_template_base,
)
from etsy_listings.core.render.maps import DerivedMapCache
from etsy_listings.core.render.pipeline import Layer, render_scene
from etsy_listings.core.render.swatch import sample_swatch
from etsy_listings.core.render.types import RGB, RGBA
from etsy_listings.core.workspace.facts import template_info
from etsy_listings.core.workspace.template_state import TemplateLoaded, template_state
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.core.workspace.yaml_source import without_top_level_key

PREVIEW_WORKERS = 2
"""Maximum full-size preview renders in flight.

Rendering is CPU-heavy but each scene also holds several full-resolution image
arrays. Two workers materially shortens a multi-image plan without multiplying
peak memory by the size of a typical Etsy gallery.
"""


def _copy_preview(source: Path, target: Path) -> None:
    """Copy ``source`` over ``target`` atomically while retaining ``source``.

    A direct ``copyfile`` can leave a partial render if the process stops
    mid-copy. The temporary file lives beside the render so ``os.replace`` is
    an atomic same-filesystem operation, preserving the crash safety promotion
    had when it consumed previews directly.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copyfile(source, temporary)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class ResolvedLayer:
    colour: str | None
    """The garment colour this layer depicts -- a placement's own colour in a
    ``multiple`` scene, the scene's colour otherwise. What artwork resolution
    asks by, and part of the recipe: repointing a placement at a different
    colour changes what should be rendered even when the geometry does not."""
    design: Path
    design_hash: str
    """The design file's content hash -- the layer's design identity (ADR-0053).
    Not its ref and not a ``design:`` key, so a renamed file or a reshaped
    map that prints the same bytes hashes the same."""
    bounding_box: BoundingBox
    """The template's own box for this layer, whichever renderer draws it:
    where every scene samples its swatch. A listing's position never moves
    it -- the swatch reads the garment's colour, not the print (template
    positions plan PR 3) -- so Photo warp's homography target is the
    :class:`RenderConfig`'s box instead, which does follow the listing."""
    placement_id: str | None = None


@dataclass(frozen=True)
class PhotoWarpRender:
    """A scene the pure Photo warp passes draw: one frozen
    :class:`RenderConfig` per layer, in paint order, which is all of the
    template that decides its pixels besides the photo and artwork."""

    configs: tuple[RenderConfig, ...]

    @property
    def wants_height(self) -> bool:
        return any(cfg.displace.enabled for cfg in self.configs)

    @property
    def wants_luminance(self) -> bool:
        return any(cfg.shade.enabled for cfg in self.configs)


@dataclass(frozen=True)
class PreparedRender:
    inputs: PreparationInputs
    appearance: MarigoldAppearance
    identity: str
    map_content: str
    """The accepted generation's content digest, recorded in the recipe --
    combined with each position fit's digest when the listing positions a
    layer (option B), so only positioned scenes' lockfiles change."""
    boxes: LayerBoxes = field(default_factory=dict)
    """The listing's saved position, which ``apply()`` leases the fits for."""


SceneRender = PhotoWarpRender | PreparedRender
"""How one scene's pixels are made: the template's renderer, resolved."""


@dataclass(frozen=True)
class SceneWork:
    """One render: everything it needs, resolved exactly once."""

    key: str  # "template/colour" for colour-matrix, "template" otherwise
    template: str
    colour: str | None
    kind: str
    config_file: Path
    base_image: Path
    map_key: str
    """Key for the template's ``DerivedMapCache`` -- the colour for a
    colour-matrix scene (one photo per colour, so one map per colour), the
    template name otherwise (one photo, one map)."""
    layers: tuple[ResolvedLayer, ...]
    output: Path
    render: SceneRender

    def recipe(self) -> dict[str, object]:
        """The part of this scene that decides its pixels, for the input hash.

        Each layer carries its design's content hash, which *is* its design
        identity (ADR-0053) -- there is no other name for which file a layer
        prints that survives a rename. The template's and the photo's bytes
        are hashed separately (``template_hash``, ``base_hash``), and no path
        enters: a path is not a hash. Prepared scenes record accepted map
        content and appearance here; their canonical pixel identity also
        contains ordered artwork and the target photo (ADR-0054).

        Every lockfile records this as ``scene_config``, so its shape and key
        order are fixed: a changed byte re-renders every listing.
        """
        match self.render:
            case PreparedRender(appearance=appearance, map_content=map_content):
                return {
                    "template": self.template,
                    "kind": self.kind,
                    "renderer": "marigold",
                    "map_content": map_content,
                    "appearance": appearance.model_dump(mode="json"),
                    "layers": [
                        {
                            "placement_id": layer.placement_id,
                            "design_hash": layer.design_hash,
                            "colour": layer.colour,
                        }
                        for layer in self.layers
                    ],
                }
            case PhotoWarpRender(configs=configs):
                return {
                    "template": self.template,
                    "kind": self.kind,
                    "layers": [
                        {
                            "colour": layer.colour,
                            "design_hash": layer.design_hash,
                            "render_config": cfg.canonical_json(),
                        }
                        for layer, cfg in zip(self.layers, configs, strict=True)
                    ],
                }

    def inputs(self, relative: Callable[[Path], str]) -> tuple[str, ...]:
        designs: dict[str, None] = {}
        for layer in self.layers:
            designs.setdefault(relative(layer.design), None)
        return (*designs, relative(self.config_file), relative(self.base_image))


@dataclass(frozen=True)
class RenderDesired:
    listing: str
    root: Path
    """The workspace root, purely so paths can be reported workspace-relative.
    Absolute and machine-specific, so it never enters a hash -- see
    ``_input_hash``, which names the fields that do."""
    works: tuple[SceneWork, ...]  # first-seen media order, deduped
    template_hash: dict[str, str]  # template name -> _template_hash of its template.yaml
    base_hash: dict[str, str]  # scene key -> sha256 of that scene's photo
    preview_exists: dict[str, bool] = field(default_factory=dict)
    """Scene key -> whether ``Workspace.preview_file`` already holds a preview
    matching that scene's current :func:`scene_hash`, checked once by
    ``desired()`` -- the one place this stage already does I/O beyond
    hashing. Feeds :meth:`RenderStage.snapshot`'s ``preview`` field. Defaults
    to empty so a ``RenderDesired`` built by hand (a unit test exercising
    :func:`scene_hash` in isolation) doesn't have to know this exists."""

    @property
    def scenes(self) -> tuple[str, ...]:
        return tuple(work.key for work in self.works)

    def relative(self, path: Path) -> str:
        return to_workspace_relative_posix(self.root, path)


def _scene_payload(
    work: SceneWork,
    *,
    template_hash: Mapping[str, str],
    base_hash: Mapping[str, str],
) -> dict[str, object]:
    return {
        "template": work.template,
        "template_hash": template_hash[work.template],
        "base_hash": base_hash[work.key],
        "recipe": work.recipe(),
    }


def scene_hash(desired: RenderDesired, work: SceneWork) -> str:
    match work.render:
        case PreparedRender(identity=identity):
            return identity
        case PhotoWarpRender():
            return canonical_hash(
                _scene_payload(
                    work,
                    template_hash=desired.template_hash,
                    base_hash=desired.base_hash,
                )
            )


def _hash_token(digest: str) -> str:
    """``scene_hash``'s value, stripped of its ``sha256:`` prefix.

    A colon is not a valid filename character on Windows, and
    ``Workspace.preview_file`` treats the hash as a single path segment the
    same way it does a colour or a template name -- which already refuses one
    (see its docstring). Every call site that turns a ``scene_hash`` into a
    path goes through this first.
    """
    return digest.removeprefix("sha256:")


RenderSceneState = Literal["cached", "stale", "missing"]


class RenderSceneSnapshot(BaseModel):
    """One scene's domain facts for the before/after review.

    ``state`` answers "would this scene's rendered output change, and is it
    even there" -- ``cached`` when neither is true, ``stale`` when the scene's
    own hash has moved since the last apply, ``missing`` when the file itself
    is absent (which wins over a hash comparison: a hash proves nothing about
    a file that was deleted). ``preview`` answers a different question --
    whether a full-size preview is already sitting in the cache for the
    *current* state, which is what tells a caller whether ``preview()`` has
    anything left to do for this scene.
    """

    model_config = ConfigDict(frozen=True)

    scene: str
    template: str
    colour: str | None
    state: RenderSceneState
    preview: bool
    scene_hash: str
    """:func:`scene_hash` as this plan computed it, without its ``sha256:``
    prefix -- what names this plan's preview file, so the review can ask for
    exactly that file rather than have the server plan the listing again."""


class RenderSnapshot(BaseModel):
    """Every referenced scene, in media order -- what the before/after review
    needs and a ``Plan`` (changes only) cannot supply."""

    model_config = ConfigDict(frozen=True)

    scenes: tuple[RenderSceneSnapshot, ...]


class RenderApplied(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    input_hash: str
    scenes: tuple[str, ...]
    scene_hashes: dict[str, str] = {}
    """Scene key -> :func:`scene_hash` at the last apply. Defaulted, not
    required: a lockfile written before this field existed decodes as if every
    scene's map were empty, which :meth:`RenderStage.snapshot` already reads
    as "no record to compare against" -- the same answer a scene that has
    never been applied gets."""


@dataclass(frozen=True)
class RenderLive:
    outputs_present: dict[str, bool]  # scene key -> its render file exists
    scene_hashes: dict[str, str] = field(default_factory=dict)
    """``applied.scene_hashes``, carried through unchanged. ``read_live``
    has ``applied`` and ``snapshot`` does not -- this is how the value one
    decoded and the other needs to compare against reaches the second without
    a second decode of the stage's own subtree."""


def _scene_key(template: str, colour: str | None) -> str:
    return f"{template}/{colour}" if colour is not None else template


def _split_scene_key(scene: str) -> tuple[str, str | None]:
    if "/" in scene:
        template, colour = scene.split("/", 1)
        return template, colour
    return scene, None


def _render_path(workspace: Workspace, listing: str, scene: str) -> Path:
    template, colour = _split_scene_key(scene)
    return workspace.render_file(listing, template, colour)


DesignFor = Callable[[str | None, str], tuple[Path, str] | Blocked]
"""``(depicted colour, template) -> (design file, its content hash)``, or the
refusal when that colour resolves to no file."""


def _layer_specs(
    template_cfg: AnyTemplate, colour: str | None
) -> list[tuple[str | None, str | None, BoundingBox]]:
    """``(depicted colour, placement ID, bounding box)`` per layer, in paint
    order -- the template's own geometry, whichever renderer draws it."""
    return [
        (depicted, placement, box)
        for (depicted, placement), box in zip(
            scene_colours(template_cfg, colour), scene_boxes(template_cfg), strict=True
        )
    ]


def _prepared_layers(
    layers: Sequence[ResolvedLayer], design: Callable[[Path], RGBA]
) -> list[PreparedLayer]:
    return [PreparedLayer(design(layer.design), layer.placement_id) for layer in layers]


@dataclass(frozen=True)
class _SceneRef:
    template_name: str
    template_cfg: AnyTemplate
    colour: str | None
    boxes: LayerBoxes
    """The listing's saved position for this template (ADR-0058); empty
    renders the template's own boxes."""


def _resolve_layers(ref: _SceneRef, design_for: DesignFor) -> list[ResolvedLayer] | Blocked:
    layers = []
    for layer_colour, placement_id, box in _layer_specs(ref.template_cfg, ref.colour):
        design = design_for(layer_colour, ref.template_name)
        if isinstance(design, Blocked):
            return design
        path, digest = design
        layers.append(
            ResolvedLayer(
                colour=layer_colour,
                design=path,
                design_hash=digest,
                bounding_box=box,
                placement_id=placement_id,
            )
        )
    return layers


def _scene_render(
    workspace: Workspace, ref: _SceneRef, photo: Path, layers: Sequence[ResolvedLayer]
) -> SceneRender | Blocked:
    renderer = ref.template_cfg.renderer
    if isinstance(renderer, PhotoWarpRenderer):
        return PhotoWarpRender(
            configs=tuple(cfg for _, cfg in scene_layers(ref.template_cfg, ref.colour, ref.boxes))
        )
    appearance = renderer.config.appearance
    try:
        with lease_scene(
            workspace,
            ref.template_name,
            Composition(
                base=load_template_base(photo),
                layers=_prepared_layers(layers, load_design),
                appearance=appearance,
                boxes=ref.boxes,
            ),
        ) as scene:
            return PreparedRender(
                inputs=scene.inputs,
                appearance=appearance,
                identity=scene.identity,
                map_content=scene.map_content,
                boxes=ref.boxes,
            )
    except ArtifactError as exc:
        return Blocked(str(exc))


def _resolve_scene(
    *,
    workspace: Workspace,
    listing: str,
    design_for: DesignFor,
    ref: _SceneRef,
) -> SceneWork | Blocked:
    template_name, colour = ref.template_name, ref.colour
    kind = ref.template_cfg.kind
    blocked = check_scene_colour(template_name, kind, colour)
    if blocked is not None:
        return blocked

    photo = workspace.scene_photo(template_name, colour)
    blocked = check_render_photo(template_name, colour, photo.path)
    if blocked is not None:
        return blocked

    layers = _resolve_layers(ref, design_for)
    if isinstance(layers, Blocked):
        return layers
    render = _scene_render(workspace, ref, photo.path, layers)
    if isinstance(render, Blocked):
        return render
    return SceneWork(
        key=_scene_key(template_name, colour),
        template=template_name,
        colour=colour,
        kind=kind,
        config_file=workspace.template_config_file(template_name),
        base_image=photo.path,
        map_key=photo.map_key,
        layers=tuple(layers),
        output=workspace.render_file(listing, template_name, colour),
        render=render,
    )


def _referenced_scenes(listing_cfg: Listing) -> list[tuple[str, str | None]]:
    referenced: dict[tuple[str, str | None], None] = {}
    for entry in listing_cfg.media:
        if isinstance(entry, TemplateMediaEntry):
            referenced.setdefault((entry.template, entry.colour), None)
    return list(referenced)


@dataclass(frozen=True)
class _Templates:
    configs: dict[str, AnyTemplate]
    hashes: dict[str, str]


def _template_hash(path: Path) -> str:
    return hash_bytes(without_top_level_key(path.read_bytes(), "labels"))


def _load_template(workspace: Workspace, template_name: str) -> tuple[AnyTemplate, str] | Blocked:
    config_path = workspace.template_config_file(template_name)
    blocked = check_render_template(template_name, config_path)
    if blocked is not None:
        return blocked
    digest = _template_hash(config_path)
    state = template_state(workspace, template_name)
    if not isinstance(state, TemplateLoaded):
        return Blocked(state.reason)
    return state.config, digest


def _load_templates(
    workspace: Workspace, referenced: list[tuple[str, str | None]]
) -> _Templates | Blocked:
    templates = _Templates(configs={}, hashes={})
    for template_name, _ in referenced:
        if template_name in templates.configs:
            continue
        loaded = _load_template(workspace, template_name)
        if isinstance(loaded, Blocked):
            return loaded
        templates.configs[template_name], templates.hashes[template_name] = loaded
    return templates


def _check_template_inputs(
    workspace: Workspace, listing: str, listing_cfg: Listing, templates: _Templates
) -> Blocked | None:
    # ADR-0058: name refused positions before map readiness, which a fix to
    # the listing would not change.
    if listing_cfg.template_positions:
        settings = workspace.settings_or_problem()
        if isinstance(settings, SettingsProblem):
            return Blocked(settings.message)
        blocked = check_template_positions(
            listing_cfg, templates.configs, settings.template_positions, name=listing
        )
        if blocked is not None:
            return blocked
    for name, config in templates.configs.items():
        maps = template_readiness(workspace, name, config)
        blocked = check_prepared_maps(name, None if maps.can_render else maps.message)
        if blocked is not None:
            return blocked
    return None


class _DesignFiles:
    def __init__(
        self, workspace: Workspace, listing_cfg: Listing, profile: GarmentProfile, listing_dir: Path
    ) -> None:
        self._workspace = workspace
        self._listing_cfg = listing_cfg
        self._profile = profile
        self._listing_dir = listing_dir
        self._files: dict[str, tuple[Path, str]] = {}

    def __call__(self, colour: str | None, template: str) -> tuple[Path, str] | Blocked:
        ref = resolved_design(
            self._listing_cfg.design, colour, self._profile.colors, where=f"template {template!r}"
        )
        if isinstance(ref, Blocked):
            return ref
        if ref not in self._files:
            path = self._workspace.resolve_ref(ref, listing_dir=self._listing_dir)
            if not path.is_file():
                return Blocked(f"design file not found: {ref}")
            self._files[ref] = (path, hash_file(path))
        return self._files[ref]


def _resolve_scenes(
    workspace: Workspace,
    listing: str,
    listing_cfg: Listing,
    design_for: DesignFor,
    templates: _Templates,
) -> tuple[list[SceneWork], dict[str, str]] | Blocked:
    base_hash: dict[str, str] = {}
    works: list[SceneWork] = []
    for template_name, colour in _referenced_scenes(listing_cfg):
        work = _resolve_scene(
            workspace=workspace,
            listing=listing,
            design_for=design_for,
            ref=_SceneRef(
                template_name,
                templates.configs[template_name],
                colour,
                layer_boxes(listing_cfg.template_positions, template_name),
            ),
        )
        if isinstance(work, Blocked):
            return work
        works.append(work)

        # Per scene, not per template: a colour-matrix set has one photo per colour.
        base_hash[work.key] = hash_file(work.base_image)
    return works, base_hash


PreviewRenderer = Callable[[Workspace, SceneWork, Path], None]


class _PreviewSubmitter:
    def __init__(
        self,
        pool: ThreadPoolExecutor,
        jobs: Iterator[tuple[SceneWork, Path]],
        should_stop: Callable[[], bool],
        render: Callable[[SceneWork, Path], None],
    ) -> None:
        self._pool = pool
        self._jobs = jobs
        self._should_stop = should_stop
        self._render = render
        self.futures: dict[Future[None], SceneWork] = {}

    def submit(self, count: int) -> None:
        for _ in range(count):
            if not self._submit_one():
                return

    def _submit_one(self) -> bool:
        if self._should_stop():
            return False
        try:
            work, target = next(self._jobs)
        except StopIteration:
            return False
        self.futures[self._pool.submit(self._render, work, target)] = work
        return True


@dataclass
class _PreviewBatch:
    workspace: Workspace
    desired: RenderDesired
    should_stop: Callable[[], bool]
    on_ready: Callable[[SceneWork], None] | None
    ready: list[SceneWork] = field(default_factory=list)

    def _mark_ready(self, work: SceneWork) -> None:
        self.ready.append(work)
        if self.on_ready is not None:
            self.on_ready(work)

    def collect(self, needed: set[str]) -> list[tuple[SceneWork, Path]]:
        pending: list[tuple[SceneWork, Path]] = []
        for work in self.desired.works:
            if work.key not in needed:
                continue
            if self.should_stop():
                break
            target = self.workspace.preview_file(
                self.desired.listing,
                work.template,
                work.colour,
                _hash_token(scene_hash(self.desired, work)),
            )
            if target.is_file():
                self._mark_ready(work)
            else:
                pending.append((work, target))
        return pending

    def render(self, pending: list[tuple[SceneWork, Path]], renderer: PreviewRenderer) -> None:
        workers = min(PREVIEW_WORKERS, len(pending))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="render-preview") as pool:
            submitter = _PreviewSubmitter(
                pool, iter(pending), self.should_stop, partial(renderer, self.workspace)
            )
            submitter.submit(workers)
            while submitter.futures:
                finished, _ = wait(submitter.futures, return_when=FIRST_COMPLETED)
                for future in finished:
                    work = submitter.futures.pop(future)
                    future.result()
                    self._mark_ready(work)
                submitter.submit(len(finished))


@dataclass
class _PhotoWarpWriter:
    """Writes Photo warp scenes for one preview job or one whole apply.
    ``designs`` memoises decoded artwork and its pixel identity across the
    scenes it writes; the identity is computed from the arrays composed."""

    workspace: Workspace
    designs: dict[Path, tuple[RGBA, str]] = field(default_factory=dict)

    def write(self, work: SceneWork, render: PhotoWarpRender, target: Path, base: RGB) -> None:
        designs = self.designs
        for layer in work.layers:
            if layer.design not in designs:
                pixels = load_design(layer.design)
                designs[layer.design] = (pixels, artwork_identity(pixels))
        layers = list(zip(work.layers, render.configs, strict=True))
        identity = photo_warp_scene_identity(
            photo_pixels=photo_digest(base),
            layers=[(cfg, designs[layer.design][1]) for layer, cfg in layers],
        )

        def compose() -> bytes:
            map_cache = DerivedMapCache(self.workspace.template_derived_dir(work.template))
            image = render_scene(
                base,
                [Layer(design=designs[layer.design][0], cfg=cfg) for layer, cfg in layers],
                height=map_cache.height(work.map_key, base) if render.wants_height else None,
                luminance=(
                    map_cache.luminance(work.map_key, base) if render.wants_luminance else None
                ),
            )
            return encode_png(image, compression=PHOTO_WARP_PNG_COMPRESSION)

        write_atomic(target, SceneCache(self.workspace).get_or_compose(identity, compose))


class RenderStage(Stage[RenderDesired, RenderApplied, RenderLive]):
    name = "render"
    local = True
    group: str | None = None
    applied_model = RenderApplied

    @override
    def desired(
        self, ctx: RunContext, listing: str, applied: RenderApplied | None
    ) -> RenderDesired | Blocked:
        del applied
        workspace = ctx.workspace
        listing_cfg = workspace.load_listing(listing)
        blocked = check_garment_profile_chosen(listing_cfg.garment_profile)
        if blocked is not None:
            return blocked
        profile = workspace.load_garment_profile(listing_cfg.garment_profile)

        referenced = _referenced_scenes(listing_cfg)
        templates = _load_templates(workspace, referenced)
        if isinstance(templates, Blocked):
            return templates

        blocked = _check_template_inputs(workspace, listing, listing_cfg, templates)
        if blocked is not None:
            return blocked

        blocked = check_artwork(
            listing_cfg,
            profile,
            {
                name: template_info(workspace, name, config)
                for name, config in templates.configs.items()
            },
        )
        if blocked is not None:
            return blocked

        design_for = _DesignFiles(workspace, listing_cfg, profile, workspace.listing_dir(listing))
        scenes = _resolve_scenes(workspace, listing, listing_cfg, design_for, templates)
        if isinstance(scenes, Blocked):
            return scenes
        works, base_hash = scenes

        desired = RenderDesired(
            listing=listing,
            root=workspace.root,
            works=tuple(works),
            template_hash=templates.hashes,
            base_hash=base_hash,
        )
        # ADR-0040: has a preview already been rendered for each scene's *current*
        # state? Checked here, once, because this is the one place the stage
        # already does I/O beyond hashing (this method's own docstring) --
        # `snapshot()` has no workspace to ask, and by the time `preview()`
        # runs this is exactly the question it needs answered too.
        preview_exists = {
            work.key: workspace.preview_file(
                listing, work.template, work.colour, _hash_token(scene_hash(desired, work))
            ).is_file()
            for work in desired.works
        }
        return replace(desired, preview_exists=preview_exists)

    @override
    def read_live(
        self, ctx: RunContext, listing: str, lock: Lockfile, applied: RenderApplied | None
    ) -> RenderLive | None:
        """Does what the lockfile claims was rendered still exist?

        A stat per scene, deliberately not a re-hash of every PNG: a
        ``plan --all`` over a real catalogue would otherwise read every
        rendered megabyte on every invocation, to answer a question the
        separate ``outputs`` axis already exists to answer at upload time.
        """
        del lock
        if applied is None:
            return None
        return RenderLive(
            outputs_present={
                scene: _render_path(ctx.workspace, listing, scene).is_file()
                for scene in applied.scenes
            },
            scene_hashes=dict(applied.scene_hashes),
        )

    @override
    def plan(
        self, desired: RenderDesired, applied: RenderApplied | None, live: RenderLive | None
    ) -> Verdict:
        if applied is None:
            return self._will_run(desired, "no previous render", missing=())
        if applied.input_hash != self._input_hash(desired):
            return self._will_run(desired, "design or template changed", missing=())
        if applied.scenes != desired.scenes:
            return self._will_run(desired, "referenced scenes changed", missing=())

        missing = tuple(
            scene
            for scene in desired.scenes
            if live is not None and not live.outputs_present.get(scene, False)
        )
        if missing:
            noun = "file" if len(missing) == 1 else "files"
            return self._will_run(
                desired, f"{len(missing)} rendered {noun} missing from the cache", missing=missing
            )
        return Verdict.no_work()

    def _will_run(
        self, desired: RenderDesired, reason: str, *, missing: tuple[str, ...]
    ) -> Verdict:
        return Verdict.work(reason, actions=self._actions(desired, missing))

    def _actions(self, desired: RenderDesired, missing: tuple[str, ...]) -> tuple[Action, ...]:
        missing_set = set(missing)
        relative = desired.relative
        return tuple(
            Action(
                description=f"render {work.key}",
                inputs=work.inputs(relative),
                outputs=(relative(work.output),),
                missing_outputs=(relative(work.output),) if work.key in missing_set else (),
            )
            for work in desired.works
        )

    @override
    def snapshot(self, desired: RenderDesired, live: RenderLive | None) -> RenderSnapshot:
        scenes = []
        for work in desired.works:
            exists = live.outputs_present.get(work.key, False) if live is not None else False
            previous = live.scene_hashes.get(work.key) if live is not None else None
            state: RenderSceneState
            if not exists:
                state = "missing"
            elif previous == scene_hash(desired, work):
                state = "cached"
            else:
                state = "stale"
            scenes.append(
                RenderSceneSnapshot(
                    scene=work.key,
                    template=work.template,
                    colour=work.colour,
                    state=state,
                    preview=desired.preview_exists.get(work.key, False),
                    scene_hash=_hash_token(scene_hash(desired, work)),
                )
            )
        return RenderSnapshot(scenes=tuple(scenes))

    @override
    def rewrites(
        self, ctx: RunContext, desired: RenderDesired, live: RenderLive | None
    ) -> dict[Path, Path | None]:
        """Each ``stale`` or ``missing`` scene's render output, mapped to the
        preview :meth:`apply` will promote into it, or ``None`` before
        :meth:`preview` has rendered one.

        A ``cached`` scene is left out: apply writes it again, but with the
        bytes already on disk, so a stage reading it now reads what it will
        get. The preview is the exact file apply copies (ADR-0040), which is
        what lets a plan say whether a re-rendered image actually differs.
        """
        changing = {
            scene.scene for scene in self.snapshot(desired, live).scenes if scene.state != "cached"
        }
        rewrites: dict[Path, Path | None] = {}
        for work in desired.works:
            if work.key not in changing:
                continue
            preview = ctx.workspace.preview_file(
                desired.listing, work.template, work.colour, _hash_token(scene_hash(desired, work))
            )
            rewrites[work.output] = preview if preview.is_file() else None
        return rewrites

    def preview(
        self,
        ctx: RunContext,
        desired: RenderDesired,
        live: RenderLive | None,
        *,
        should_stop: Callable[[], bool] = lambda: False,
        on_ready: Callable[[SceneWork], None] | None = None,
    ) -> tuple[SceneWork, ...]:
        """Up to :data:`PREVIEW_WORKERS` scenes render concurrently. ``should_stop``
        is checked before each submission, so cancellation starts no more work;
        the small number already in flight is allowed to finish without leaving
        a half-written file. ``on_ready`` fires on this calling thread as each
        file becomes available, rather than making the UI wait for the entire
        gallery before it can reveal the first image.
        """
        workspace = ctx.workspace
        snapshot = self.snapshot(desired, live)
        needed = {s.scene for s in snapshot.scenes if s.state in ("stale", "missing")}
        batch = _PreviewBatch(workspace, desired, should_stop, on_ready)
        pending = batch.collect(needed)
        if pending:
            batch.render(pending, self._render_preview)
        self._prune_previews(workspace, desired)
        return tuple(batch.ready)

    @staticmethod
    def _render_preview(workspace: Workspace, work: SceneWork, target: Path) -> None:
        """Render one preview job with caches local to its worker."""
        match work.render:
            case PreparedRender() as prepared:
                RenderStage._render_prepared(workspace, work, prepared, target)
            case PhotoWarpRender() as photo_warp:
                _PhotoWarpWriter(workspace).write(
                    work, photo_warp, target, load_template_base(work.base_image)
                )

    @staticmethod
    def _write_scene(
        work: SceneWork, preview: Path, base: RGB, photo_warp: _PhotoWarpWriter
    ) -> None:
        match work.render:
            case PreparedRender() as prepared:
                RenderStage._render_prepared(
                    photo_warp.workspace, work, prepared, work.output, preview=preview
                )
            case PhotoWarpRender() if preview.is_file():
                _copy_preview(preview, work.output)
            case PhotoWarpRender() as render:
                photo_warp.write(work, render, work.output, base)

    @staticmethod
    def _render_prepared(
        workspace: Workspace,
        work: SceneWork,
        render: PreparedRender,
        target: Path,
        *,
        preview: Path | None = None,
    ) -> None:
        def inputs_changed() -> None:
            # S01 TRY301: the stage turns this into a block; the raise stays out of its try.
            raise ArtifactError("Render inputs changed; plan the listing again")

        try:
            with lease_scene(
                workspace,
                work.template,
                Composition(
                    base=load_template_base(work.base_image),
                    layers=_prepared_layers(work.layers, load_design),
                    appearance=render.appearance,
                    boxes=render.boxes,
                ),
                expected=render.inputs,
            ) as scene:
                if scene.identity != render.identity:
                    inputs_changed()
                if preview is not None and preview.is_file():
                    _copy_preview(preview, target)
                    return
                # Keyed by the identity just checked against the plan, which
                # lease_scene computed from the decoded pixels.
                write_atomic(target, scene.encoded(SceneCache(workspace)))
        except ArtifactError as exc:
            raise StageBlockedError(str(exc)) from exc

    def _prune_previews(self, workspace: Workspace, desired: RenderDesired) -> None:
        valid: dict[str, set[str]] = {}
        for work in desired.works:
            name = workspace.preview_file(
                desired.listing, work.template, work.colour, _hash_token(scene_hash(desired, work))
            ).name
            valid.setdefault(work.template, set()).add(name)
        workspace.prune_previews(desired.listing, valid)

    @override
    def apply(
        self,
        ctx: RunContext,
        desired: RenderDesired,
        applied: RenderApplied | None = None,
        live: RenderLive | None = None,
        lock: Lockfile | None = None,
    ) -> StageApplyResult:
        workspace = ctx.workspace
        photo_warp = _PhotoWarpWriter(workspace)
        outputs: dict[str, str] = {}

        for work in desired.works:
            base = load_template_base(work.base_image)
            preview_path = workspace.preview_file(
                desired.listing, work.template, work.colour, _hash_token(scene_hash(desired, work))
            )
            self._write_scene(work, preview_path, base, photo_warp)
            outputs[desired.relative(work.output)] = hash_file(work.output)

            swatches: tuple[Swatch, ...] = tuple(
                sample_swatch(base, layer.bounding_box) for layer in work.layers
            )
            ctx.emit(f"rendered {work.key}", swatches=swatches)

        document = {
            "input_hash": self._input_hash(desired),
            "scene_config": {work.key: work.recipe() for work in desired.works},
            "scenes": list(desired.scenes),
            "scene_hashes": {work.key: scene_hash(desired, work) for work in desired.works},
        }
        return StageApplyResult(applied=document, outputs=outputs)

    @override
    def review_hash(self, desired: RenderDesired) -> str:
        return self._input_hash(desired)

    @staticmethod
    def _input_hash(desired: RenderDesired) -> str:
        if any(isinstance(work.render, PreparedRender) for work in desired.works):
            return canonical_hash(
                {"scenes": {work.key: scene_hash(desired, work) for work in desired.works}}
            )
        payload: dict[str, object] = {
            "template_hash": desired.template_hash,
            "base_hash": desired.base_hash,
            "scene_config": {work.key: work.recipe() for work in desired.works},
        }
        return canonical_hash(payload)

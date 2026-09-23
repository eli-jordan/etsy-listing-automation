"""The ``render`` stage: local-only (no remote state), wires the pure render
pipeline into plan/apply.

Its ``desired()`` does the I/O the render *passes* deliberately don't (A7):
loading the listing/garment-profile/template config and hashing the design + template
assets. ``read_live()`` looks at what is actually on disk under
``.cache/renders/``. ``apply()`` is the one place renders actually happen and
get written to ``.cache/renders/{listing}/{template}/...`` (PRD: rendered
mockups persist in the gitignored cache, keyed by listing, never committed;
namespaced by template since a listing can reference several -- see
``Workspace.render_file``).

Two questions decide whether work happens, and both have to be asked. The
``input_hash`` answers "would a render produce something different?"; the
outputs on disk answer "is what a previous render produced still there?". The
cache is gitignored and fully derivable, so it is a directory people delete --
checking only the hash made ``plan`` report "No changes." over a half-empty
render cache, and ``apply`` then did nothing to restore it.

A template is exactly one of three kinds (multi-placement redesign,
docs/multi-placement-rendering.md). A scene renders if, and only if, some
entry in the listing's ``media:`` list references it -- rendering is driven
purely by ``media``, not by ``listing.colors`` (item 4 of that doc).

The kind is consulted in exactly one place, :func:`_resolve_scene`, which
turns each referenced ``(template, colour)`` into a :class:`SceneWork`: the
photo to composite over, the derived-map key, and the resolved layers.
``desired()`` hashes those; ``apply()`` renders them. Neither re-reads the
config nor re-resolves an artwork, which is what keeps the hash and the pixels
describing the same thing.

A32: ``preview()`` renders full-size, ahead of ``apply()`` and through the
same pipeline, to a content-addressed cache under ``.cache/previews/`` keyed
by :func:`scene_hash` -- a *third*, narrower hash axis alongside
``input_hash`` (whole-listing: would a re-render differ at all) and
``outputs`` (per-file: does what is on disk match what was uploaded), scoped
to one scene's own inputs so a UI plan run can preview only the scenes that
actually changed rather than every scene the moment any one of them does.
``apply()`` promotes a matching preview by copying its exact bytes instead of
rendering again; ``snapshot()`` is what tells a caller which scenes need one.
The preview remains addressable while the rest of apply is running, so a UI
that reconnects mid-run does not lose images already promoted to renders.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from collections.abc import Callable, Mapping
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from etsy_listings.config.listing import TemplateMediaEntry
from etsy_listings.engine.change import Action, Verdict
from etsy_listings.engine.context import RunContext, Swatch
from etsy_listings.engine.lock import (
    Lockfile,
    canonical_hash,
    hash_file,
    to_workspace_relative_posix,
)
from etsy_listings.engine.stage import Blocked, StageApplyResult
from etsy_listings.engine.stages.gates import check_garment_profile_chosen
from etsy_listings.engine.stages.placement import DesignPlacement
from etsy_listings.render.config import (
    AnyTemplate,
    ColourMatrixTemplate,
    RenderConfig,
    SingleTemplate,
)
from etsy_listings.render.io import load_design, load_template_base, save_png
from etsy_listings.render.maps import DerivedMapCache
from etsy_listings.render.pipeline import Layer, render_scene
from etsy_listings.render.swatch import sample_swatch
from etsy_listings.render.types import RGBA
from etsy_listings.workspace.workspace import Workspace, remove_tree

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
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


class TemplateAssetError(FileNotFoundError):
    def __init__(self, template: str, colour: str | None, path: object) -> None:
        where = f"colour {colour!r}" if colour is not None else "its scene"
        super().__init__(f"template {template!r}: no mockup base image for {where} at {path}")


class TemplateNotFoundError(FileNotFoundError):
    def __init__(self, template: str, path: object) -> None:
        super().__init__(
            f"media references template {template!r}, but no template.yaml exists at {path}"
        )


class MediaColourMismatchError(ValueError):
    def __init__(self, template: str, kind: str, colour: str | None) -> None:
        if kind == "colour-matrix":
            super().__init__(
                f"media entry for template {template!r} (colour-matrix kind) needs a colour"
            )
        else:
            super().__init__(
                f"media entry for template {template!r} ({kind} kind) must not set colour "
                f"{colour!r} -- it has exactly one output"
            )


@dataclass(frozen=True)
class ResolvedLayer:
    """One design, placed at one bounding box, inside a scene.

    ``artwork`` has already been resolved through
    :meth:`~etsy_listings.engine.stages.placement.DesignPlacement.artwork_for`
    and ``design`` is the file it landed on -- so nothing downstream repeats
    that resolution, and the answer that got hashed is the answer that gets
    rendered.
    """

    colour: str | None
    """The garment colour this layer depicts -- a placement's own colour in a
    ``multiple`` scene, the scene's colour otherwise. Context for artwork
    resolution, and part of the recipe: repointing a placement at a different
    colour changes what should be rendered even when the geometry does not."""
    artwork: str
    design: Path
    cfg: RenderConfig


@dataclass(frozen=True)
class SceneWork:
    """One render: everything it needs, resolved exactly once.

    This is the whole reason the stage no longer branches on template kind
    twice. ``desired()`` used to compute a hash payload and ``apply()`` then
    re-derived the same base image, artwork and output path from the config a
    second time, through a second set of three ``isinstance`` branches. The
    two agreeing was an invariant maintained by hand: an edit to artwork
    resolution landing in one branch and not the other would write a lockfile
    describing a render that never happened, and ``plan`` would report "No
    changes." over it forever.

    Now the kind is consulted once, here, and ``apply()`` is a loop over these
    with no branching left in it.
    """

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

    @property
    def wants_height(self) -> bool:
        return any(layer.cfg.displace.enabled for layer in self.layers)

    @property
    def wants_luminance(self) -> bool:
        return any(layer.cfg.shade.enabled for layer in self.layers)

    def recipe(self) -> dict[str, object]:
        """The part of this scene that decides its pixels, for the input hash.

        Deliberately excludes file *contents* -- those are hashed separately
        (``design_hash``, ``template_hash``, ``base_hash``), because the two
        axes answer different questions and a path is not a hash.
        """
        return {
            "template": self.template,
            "kind": self.kind,
            "layers": [
                {
                    "colour": layer.colour,
                    "artwork": layer.artwork,
                    "render_config": layer.cfg.canonical_json(),
                }
                for layer in self.layers
            ],
        }

    def inputs(self, relative: Callable[[Path], str]) -> tuple[str, ...]:
        """The files this scene reads: its designs (deduped, in layer order),
        its ``template.yaml`` and its photo."""
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
    design_hash: dict[str, str]  # artwork key -> sha256, only keys actually used
    template_hash: dict[str, str]  # template name -> sha256 of its template.yaml
    base_hash: dict[str, str]  # scene key -> sha256 of that scene's photo
    preview_exists: dict[str, bool] = field(default_factory=dict)
    """Scene key -> whether ``Workspace.preview_file`` already holds a preview
    matching that scene's current :func:`scene_hash`, checked once by
    ``desired()`` (A32) -- the one place this stage already does I/O beyond
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
    design_hash: Mapping[str, str],
    template_hash: Mapping[str, str],
    base_hash: Mapping[str, str],
) -> dict[str, object]:
    """The part of :func:`scene_hash`'s payload that is just a lookup --
    shared between the pure ``desired``-based call and ``desired()``'s own
    two-step construction, which has the same three dicts on hand before a
    :class:`RenderDesired` exists to call the method on.

    Restricted to this one scene: only the design hashes for *its own*
    layers, only *its* template's hash, only *its* photo's hash. A scene that
    shares nothing with another -- a different template, different artwork --
    hashes independently of it, which is the entire point of asking per scene
    rather than reading ``_input_hash``'s listing-wide answer (A32).
    """
    return {
        "template": work.template,
        "template_hash": template_hash[work.template],
        "base_hash": base_hash[work.key],
        "design_hash": {layer.artwork: design_hash[layer.artwork] for layer in work.layers},
        "recipe": work.recipe(),
    }


def scene_hash(desired: RenderDesired, work: SceneWork) -> str:
    """A32: one scene's own share of ``_input_hash``'s inputs, hashed alone.

    Two uses. ``RenderStage.snapshot`` compares this against the hash
    recorded for the scene at the last apply (:attr:`RenderApplied.scene_hashes`)
    to say ``cached`` or ``stale`` *per scene* -- ``_input_hash`` alone cannot
    answer that, because it changes the moment any scene's inputs change, which
    would mark every scene stale over one design edit. ``RenderStage.preview``
    and :meth:`Workspace.preview_file` use it as a content-addressed cache key:
    a preview already sitting under that hash is reused rather than re-rendered,
    and a preview under any other hash for this scene is stale and pruned.

    Pure, like the payload it wraps -- no I/O, so a unit test builds a
    :class:`RenderDesired` and two :class:`SceneWork` values by hand and
    changes one scene's inputs without touching the other's hash.
    """
    return canonical_hash(
        _scene_payload(
            work,
            design_hash=desired.design_hash,
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
    """One scene's domain facts for the before/after review (A30, A32).

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


class RenderSnapshot(BaseModel):
    """Every referenced scene, in media order -- what the before/after review
    needs and a ``Plan`` (changes only) cannot supply (A30)."""

    model_config = ConfigDict(frozen=True)

    scenes: tuple[RenderSceneSnapshot, ...]


class RenderApplied(BaseModel):
    """The stage's lockfile subtree, as the fields ``plan()`` and ``snapshot()``
    compare.

    A model rather than a dataclass with a hand-written ``parse``, so that
    :meth:`~etsy_listings.engine.lock.Lockfile.parse_applied_for` can decode
    it under the same rule as every other stage's document. The hand-written
    one indexed ``data["input_hash"]`` and raised ``KeyError`` on a truncated
    lockfile, where the product stage's returned ``None`` -- one rule, two
    answers, and the raising one took a whole ``--all`` batch with it.

    ``extra="ignore"``, because the written document also carries
    ``scene_config``, which nothing reads back: it is there because A2 says
    the lockfile records the verbatim last-applied document, not because this
    comparison needs it.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    input_hash: str
    scenes: tuple[str, ...]
    scene_hashes: dict[str, str] = {}
    """Scene key -> :func:`scene_hash` at the last apply (A32). Defaulted, not
    required: a lockfile written before this field existed decodes as if every
    scene's map were empty, which :meth:`RenderStage.snapshot` already reads
    as "no record to compare against" -- the same answer a scene that has
    never been applied gets."""


@dataclass(frozen=True)
class RenderLive:
    """What is on disk right now, for the scenes the lockfile claims were
    rendered. An observation only -- comparing it against desired/applied is
    ``plan()``'s job, per A2."""

    outputs_present: dict[str, bool]  # scene key -> its render file exists
    scene_hashes: dict[str, str] = field(default_factory=dict)
    """``applied.scene_hashes``, carried through unchanged (A32). ``read_live``
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


# The only thing left that reads a template's kind. Which photo a scene
# composites over, and what its derived maps cache under, are the same
# question asked at a different level -- `Workspace.scene_photo` answers both,
# so the calibrator's preview reaches them the same way (A8).
def _layer_specs(
    template_cfg: AnyTemplate, colour: str | None
) -> list[tuple[str | None, str | None, RenderConfig]]:
    """``(colour, artwork override, render config)`` per layer, in paint order."""
    if isinstance(template_cfg, ColourMatrixTemplate):
        # Same geometry in every colour's photo: a colour framed differently
        # is a `single`-kind template instead, never a per-colour override.
        return [(colour, None, template_cfg.render_config())]
    if isinstance(template_cfg, SingleTemplate):
        return [(template_cfg.colour, template_cfg.artwork, template_cfg.render_config())]
    return [
        (placement.colour, placement.artwork, template_cfg.render_config_for(placement))
        for placement in template_cfg.placements
    ]


def _resolve_scene(
    *,
    workspace: Workspace,
    listing: str,
    placement: DesignPlacement,
    template_name: str,
    template_cfg: AnyTemplate,
    colour: str | None,
) -> SceneWork:
    kind = template_cfg.kind
    if (kind == "colour-matrix") != (colour is not None):
        raise MediaColourMismatchError(template_name, kind, colour)

    photo = workspace.scene_photo(template_name, colour)
    if not photo.path.is_file():
        raise TemplateAssetError(template_name, colour, photo.path)

    layers = []
    for layer_colour, override, cfg in _layer_specs(template_cfg, colour):
        artwork = placement.artwork_for(layer_colour, template_override=override)
        layers.append(
            ResolvedLayer(
                colour=layer_colour, artwork=artwork, design=placement.paths[artwork], cfg=cfg
            )
        )

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
    )


class RenderStage:
    name = "render"
    local = True
    applied_model = RenderApplied

    def desired(
        self, ctx: RunContext, listing: str, applied: RenderApplied | None
    ) -> RenderDesired | Blocked:
        """``applied`` is unused: nothing about a *previous* render can make the
        next one refusable. The parameter is the protocol's, not this stage's
        -- the product stage needs it to refuse a garment change (PRD 37)."""
        del applied
        workspace = ctx.workspace
        listing_cfg = workspace.load_listing(listing)
        blocked = check_garment_profile_chosen(listing_cfg.garment_profile)
        if blocked is not None:
            return blocked
        profile = workspace.load_garment_profile(listing_cfg.garment_profile)
        placement = DesignPlacement.resolve(workspace, listing, listing_cfg, profile)

        referenced: dict[tuple[str, str | None], None] = {}
        for entry in listing_cfg.media:
            if isinstance(entry, TemplateMediaEntry):
                referenced.setdefault((entry.template, entry.colour), None)

        template_configs: dict[str, AnyTemplate] = {}
        template_hash: dict[str, str] = {}
        design_hash: dict[str, str] = {}
        base_hash: dict[str, str] = {}
        works: list[SceneWork] = []

        for template_name, colour in referenced:
            if template_name not in template_configs:
                config_path = workspace.template_config_file(template_name)
                if not config_path.is_file():
                    raise TemplateNotFoundError(template_name, config_path)
                # The file's own bytes, not the re-serialised model: hashing a
                # normalised dump would miss an edit that pydantic round-trips
                # away, and the question here is "did the file change?".
                template_hash[template_name] = hash_file(config_path)
                template_configs[template_name] = workspace.load_template_config(template_name)

            work = _resolve_scene(
                workspace=workspace,
                listing=listing,
                placement=placement,
                template_name=template_name,
                template_cfg=template_configs[template_name],
                colour=colour,
            )
            works.append(work)

            # Per scene, not per template. A colour-matrix set has one photo
            # per colour, and hashing only the first one (which is what
            # `setdefault` over the template name used to do) meant replacing
            # any *other* colour's photo changed no hash at all -- so `plan`
            # reported "No changes." and the stale render stayed in the cache.
            base_hash[work.key] = hash_file(work.base_image)
            for layer in work.layers:
                design_hash[layer.artwork] = hash_file(layer.design)

        desired = RenderDesired(
            listing=listing,
            root=workspace.root,
            works=tuple(works),
            design_hash=design_hash,
            template_hash=template_hash,
            base_hash=base_hash,
        )
        # A32: has a preview already been rendered for each scene's *current*
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

    def read_live(
        self, ctx: RunContext, listing: str, lock: Lockfile, applied: RenderApplied | None
    ) -> RenderLive | None:
        """Does what the lockfile claims was rendered still exist?

        A stat per scene, deliberately not a re-hash of every PNG: a
        ``plan --all`` over a real catalogue would otherwise read every
        rendered megabyte on every invocation, to answer a question the
        separate ``outputs`` axis already exists to answer at upload time.

        ``applied`` arrives decoded. This used to re-look-up and re-parse the
        stage's own subtree here, having just been handed it a line earlier in
        ``build_plan``.
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

    def snapshot(self, desired: RenderDesired, live: RenderLive | None) -> RenderSnapshot:
        """Per scene: is its current render output still correct, and is a
        full-size preview already sitting in the cache for it (A30, A32).

        ``cached``/``stale`` compares this scene's own :func:`scene_hash`
        against what :attr:`RenderLive.scene_hashes` recorded for it at the
        last apply -- not ``applied.input_hash``, which changes the moment
        *any* scene's inputs change and would mark every scene stale over one
        design edit. That would defeat the reason to ask per scene at all:
        ``preview()`` reads this to decide which scenes are worth spending a
        render on. ``missing`` wins over both when the render file itself is
        not on disk, whatever its hash says -- a hash comparison proves
        nothing about a file that was deleted.
        """
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
                )
            )
        return RenderSnapshot(scenes=tuple(scenes))

    def preview(
        self,
        ctx: RunContext,
        desired: RenderDesired,
        live: RenderLive | None,
        *,
        should_stop: Callable[[], bool] = lambda: False,
        on_ready: Callable[[SceneWork], None] | None = None,
    ) -> tuple[SceneWork, ...]:
        """Render a full-size preview for every scene :meth:`snapshot` calls
        ``stale`` or ``missing`` (A32), through the same pipeline ``apply``
        uses, to :meth:`~etsy_listings.workspace.workspace.Workspace.preview_file`;
        prune every preview this listing holds whose hash no longer matches
        any currently-referenced scene, in the same pass.

        Called after a plan has resolved, never inside one -- a plan stays
        read-only and fast, and a full-size render costs real time per scene.
        ``apply`` later promotes whatever this wrote (its own docstring),
        which is what makes calling this ahead of an ``apply`` free rather
        than double work, and what keeps a promoted file identical to a fresh
        render: both come from the same ``render_scene`` call over the same
        resolved inputs (A7).

        Up to :data:`PREVIEW_WORKERS` scenes render concurrently. ``should_stop``
        is checked before each submission, so cancellation starts no more work;
        the small number already in flight is allowed to finish without leaving
        a half-written file. ``on_ready`` fires on this calling thread as each
        file becomes available, rather than making the UI wait for the entire
        gallery before it can reveal the first image.

        Returns the scenes that end this call with a ready preview file,
        whether freshly rendered here or already current from an earlier
        call -- a caller reports one event per entry, and an entry a caller
        never sees (because ``should_stop`` cut the loop short) simply is not
        ready yet.
        """
        workspace = ctx.workspace
        snapshot = self.snapshot(desired, live)
        needed = {s.scene for s in snapshot.scenes if s.state in ("stale", "missing")}

        ready: list[SceneWork] = []
        pending: list[tuple[SceneWork, Path]] = []

        for work in desired.works:
            if work.key not in needed:
                continue
            if should_stop():
                break
            target = workspace.preview_file(
                desired.listing, work.template, work.colour, _hash_token(scene_hash(desired, work))
            )
            if target.is_file():
                ready.append(work)
                if on_ready is not None:
                    on_ready(work)
            else:
                pending.append((work, target))

        if pending:
            workers = min(PREVIEW_WORKERS, len(pending))
            jobs = iter(pending)
            futures: dict[Future[None], SceneWork] = {}

            def submit_one(pool: ThreadPoolExecutor) -> bool:
                if should_stop():
                    return False
                try:
                    work, target = next(jobs)
                except StopIteration:
                    return False
                futures[pool.submit(self._render_preview, workspace, work, target)] = work
                return True

            with ThreadPoolExecutor(
                max_workers=workers, thread_name_prefix="render-preview"
            ) as pool:
                for _ in range(workers):
                    if not submit_one(pool):
                        break
                while futures:
                    finished, _ = wait(futures, return_when=FIRST_COMPLETED)
                    for future in finished:
                        work = futures.pop(future)
                        future.result()
                        ready.append(work)
                        if on_ready is not None:
                            on_ready(work)
                    for _ in finished:
                        if not submit_one(pool):
                            break

        self._prune_previews(workspace, desired)
        return tuple(ready)

    @staticmethod
    def _render_preview(workspace: Workspace, work: SceneWork, target: Path) -> None:
        """Render one preview job with caches local to its worker."""
        base = load_template_base(work.base_image)
        map_cache = DerivedMapCache(workspace.template_derived_dir(work.template))
        height = map_cache.height(work.map_key, base) if work.wants_height else None
        luminance = map_cache.luminance(work.map_key, base) if work.wants_luminance else None
        designs: dict[Path, RGBA] = {}
        layers = []
        for layer in work.layers:
            if layer.design not in designs:
                designs[layer.design] = load_design(layer.design)
            layers.append(Layer(design=designs[layer.design], cfg=layer.cfg))
        image = render_scene(base, layers, height=height, luminance=luminance)
        save_png(image, target)

    def _prune_previews(self, workspace: Workspace, desired: RenderDesired) -> None:
        """Delete every preview file under this listing's preview directory
        that does not match one of ``desired``'s scenes at its current hash
        (A32) -- the input that made it stale is gone by the time this runs,
        so "does the current hash still name this file" is the only test
        available, and it is exactly the one a content-addressed cache is for.

        A template subdirectory for a template no longer referenced at all
        (dropped from ``media:`` this run) is removed outright rather than
        left empty.
        """
        preview_root = workspace.preview_dir(desired.listing)
        if not preview_root.is_dir():
            return
        valid: dict[str, set[str]] = {}
        for work in desired.works:
            name = workspace.preview_file(
                desired.listing, work.template, work.colour, _hash_token(scene_hash(desired, work))
            ).name
            valid.setdefault(work.template, set()).add(name)
        for template_dir in preview_root.iterdir():
            if not template_dir.is_dir():
                continue
            keep = valid.get(template_dir.name)
            if keep is None:
                remove_tree(template_dir)
                continue
            for file in template_dir.glob("*.png"):
                if file.name not in keep:
                    file.unlink()

    def apply(
        self,
        ctx: RunContext,
        desired: RenderDesired,
        applied: RenderApplied | None = None,
        live: RenderLive | None = None,
        lock: Lockfile | None = None,
    ) -> StageApplyResult:
        """A flat loop over already-resolved work.

        Nothing here re-opens ``template.yaml``, re-resolves an artwork or
        re-derives a path: every one of those answers came from ``desired()``,
        which is the same object that produced ``input_hash``. That is what
        makes "what was hashed is what was rendered" true by construction
        rather than by two branch sets agreeing.

        A32: before rendering a scene, this looks for a preview
        :meth:`preview` may already have left at
        :meth:`~etsy_listings.workspace.workspace.Workspace.preview_file` for
        its current hash. If one is there it is copied into place instead of
        rendered again -- a promoted file is
        exactly the bytes a fresh render would produce, since both come from
        the same pipeline over the same resolved inputs (A7), so the ``outputs``
        hash axis cannot tell the difference and nothing is uploaded twice.

        The content-addressed preview is deliberately retained. The deploy UI
        continues to show its reviewed images while later apply stages run and
        after a browser refresh; a later preview pass prunes it when its scene
        hash is no longer current.
        """
        workspace = ctx.workspace
        design_cache: dict[Path, RGBA] = {}
        map_caches: dict[str, DerivedMapCache] = {}
        outputs: dict[str, str] = {}

        for work in desired.works:
            base = load_template_base(work.base_image)
            preview_path = workspace.preview_file(
                desired.listing, work.template, work.colour, _hash_token(scene_hash(desired, work))
            )
            if preview_path.is_file():
                # Promotion (A32): the same bytes a fresh render would
                # produce, already sitting there from an earlier `preview()`
                # call. Keep the preview addressable while this apply is in
                # progress: a refreshed deploy page still points at it.
                _copy_preview(preview_path, work.output)
            else:
                map_cache = map_caches.setdefault(
                    work.template, DerivedMapCache(workspace.template_derived_dir(work.template))
                )
                height = map_cache.height(work.map_key, base) if work.wants_height else None
                luminance = (
                    map_cache.luminance(work.map_key, base) if work.wants_luminance else None
                )

                layers = []
                for layer in work.layers:
                    if layer.design not in design_cache:
                        design_cache[layer.design] = load_design(layer.design)
                    layers.append(Layer(design=design_cache[layer.design], cfg=layer.cfg))

                image = render_scene(base, layers, height=height, luminance=luminance)
                save_png(image, work.output)
            outputs[desired.relative(work.output)] = hash_file(work.output)

            swatches: tuple[Swatch, ...] = tuple(
                sample_swatch(base, layer.cfg.bounding_box) for layer in work.layers
            )
            ctx.emit(f"rendered {work.key}", swatches=swatches)

        document = {
            "input_hash": self._input_hash(desired),
            "scene_config": {work.key: work.recipe() for work in desired.works},
            "scenes": list(desired.scenes),
            "scene_hashes": {work.key: scene_hash(desired, work) for work in desired.works},
        }
        return StageApplyResult(applied=document, outputs=outputs)

    @staticmethod
    def _input_hash(desired: RenderDesired) -> str:
        """The four axes that decide whether a re-render would differ: the
        design bytes, the template.yaml bytes, the photo bytes, and the recipe
        each scene resolved to. No absolute paths, no clock, no tool version
        (A2)."""
        payload: dict[str, object] = {
            "design_hash": desired.design_hash,
            "template_hash": desired.template_hash,
            "base_hash": desired.base_hash,
            "scene_config": {work.key: work.recipe() for work in desired.works},
        }
        return canonical_hash(payload)

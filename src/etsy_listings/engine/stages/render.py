"""The ``render`` stage: local-only (no remote state), wires the pure render
pipeline into plan/apply.

Its ``desired()`` does the I/O the render *passes* deliberately don't (A7):
loading the listing/profile/template config and hashing the design + template
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
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from etsy_listings.config.listing import Listing, TemplateMediaEntry
from etsy_listings.config.profile import Profile
from etsy_listings.engine.change import Action, StagePlan
from etsy_listings.engine.context import RunContext, Swatch
from etsy_listings.engine.lock import Lockfile, canonical_hash, to_workspace_relative_posix
from etsy_listings.engine.stage import StageApplyResult
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
from etsy_listings.workspace.workspace import Workspace


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


class ArtworkResolutionError(ValueError):
    """Names *which* key was asked for and *who* asked for it.

    Without both, the message sends you to the wrong file. A template with
    ``artwork: on-light`` over a single-file design used to report only
    "colour 'white' needs an artwork but none resolves", which reads as a
    problem with the colour or the listing -- while the demand actually came
    from the template, and ``on-light`` appeared nowhere in the message.
    """

    def __init__(
        self,
        colour: str | None,
        tone: str | None,
        available: list[str],
        *,
        wanted: str | None = None,
        source: str = "",
    ) -> None:
        detail = f"colour {colour!r}" if colour is not None else "this template"
        tone_note = f" (tone: {tone})" if tone else ""
        if wanted is not None:
            super().__init__(
                f"{detail}{tone_note}: {source} asks for artwork {wanted!r}, which the "
                f"design does not have -- it offers {available!r}. Add {wanted!r} to the "
                f"listing's design:, or remove the override."
            )
        else:
            super().__init__(
                f"{detail}{tone_note} needs an artwork but none resolves -- design offers "
                f"{available!r}; add a listing.artwork override or a matching key"
            )


def _resolve_artwork(
    *,
    colour: str | None,
    listing: Listing,
    profile: Profile,
    template_override: str | None,
) -> str:
    """Resolution order (docs/multi-placement-rendering.md item 2):
    1. ``listing.artwork[colour]`` -- explicit per-design override, wins even
       over the template's own override (deliberately -- see the doc).
    2. The template/placement's own ``artwork`` override.
    3. ``on-{profile.colour_tone[colour]}``, if that key exists in the design map.
    4. The design map's sole key, if it has exactly one entry.
    """
    keys = list(listing.design.keys())
    key_set = set(keys)

    candidate: str | None = None
    source = ""
    if colour is not None and colour in listing.artwork:
        candidate, source = listing.artwork[colour], f"the listing's artwork[{colour!r}]"
    elif template_override is not None:
        candidate, source = template_override, "the template's own artwork: override"
    elif colour is not None and colour in profile.colour_tone:
        toned = f"on-{profile.colour_tone[colour]}"
        if toned in key_set:
            candidate, source = toned, f"the profile's colour_tone[{colour!r}]"

    if candidate is None and len(keys) == 1:
        candidate, source = keys[0], "the design's sole key"

    if candidate is None or candidate not in key_set:
        tone = profile.colour_tone.get(colour) if colour is not None else None
        raise ArtworkResolutionError(colour, tone, sorted(keys), wanted=candidate, source=source)
    return candidate


@dataclass(frozen=True)
class ResolvedLayer:
    """One design, placed at one bounding box, inside a scene.

    ``artwork`` has already been resolved through :func:`_resolve_artwork` and
    ``design`` is the file it landed on -- so nothing downstream repeats that
    resolution, and the answer that got hashed is the answer that gets
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

    @property
    def scenes(self) -> tuple[str, ...]:
        return tuple(work.key for work in self.works)

    def relative(self, path: Path) -> str:
        return to_workspace_relative_posix(self.root, path)


@dataclass(frozen=True)
class RenderApplied:
    input_hash: str
    scenes: tuple[str, ...]


@dataclass(frozen=True)
class RenderLive:
    """What is on disk right now, for the scenes the lockfile claims were
    rendered. An observation only -- comparing it against desired/applied is
    ``plan()``'s job, per A2."""

    outputs_present: dict[str, bool]  # scene key -> its render file exists


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


def _hash_path(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _hash_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


# The one place template kind is consulted. It decides exactly three things --
# which photo, which derived-map key, and which layers -- and everything after
# it is shared. Compare the three near-identical ~40-line branches this
# replaced, which each also rebuilt the hash payload, the input list and the
# output path for themselves (see SceneWork's docstring).
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
    listing_cfg: Listing,
    profile: Profile,
    design_paths: dict[str, Path],
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
        artwork = _resolve_artwork(
            colour=layer_colour,
            listing=listing_cfg,
            profile=profile,
            template_override=override,
        )
        layers.append(
            ResolvedLayer(
                colour=layer_colour, artwork=artwork, design=design_paths[artwork], cfg=cfg
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

    def desired(self, ctx: RunContext, listing: str) -> RenderDesired:
        workspace = ctx.workspace
        listing_cfg = workspace.load_listing(listing)
        profile = workspace.load_profile(listing_cfg.profile)

        design_paths: dict[str, Path] = {
            key: workspace.resolve(ref, relative_to=workspace.listing_dir(listing))
            for key, ref in listing_cfg.design.items()
        }

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
                template_hash[template_name] = _hash_path(config_path)
                template_configs[template_name] = workspace.load_template_config(template_name)

            work = _resolve_scene(
                workspace=workspace,
                listing=listing,
                listing_cfg=listing_cfg,
                profile=profile,
                design_paths=design_paths,
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
            base_hash[work.key] = _hash_path(work.base_image)
            for layer in work.layers:
                design_hash[layer.artwork] = _hash_path(layer.design)

        return RenderDesired(
            listing=listing,
            root=workspace.root,
            works=tuple(works),
            design_hash=design_hash,
            template_hash=template_hash,
            base_hash=base_hash,
        )

    def last_applied(self, lock: Lockfile) -> RenderApplied | None:
        data = lock.applied.get(self.name)
        if data is None:
            return None
        return RenderApplied(input_hash=data["input_hash"], scenes=tuple(data["scenes"]))

    def read_live(self, ctx: RunContext, listing: str, lock: Lockfile) -> RenderLive | None:
        """Does what the lockfile claims was rendered still exist?

        A stat per scene, deliberately not a re-hash of every PNG: a
        ``plan --all`` over a real catalogue would otherwise read every
        rendered megabyte on every invocation, to answer a question the
        separate ``outputs`` axis already exists to answer at upload time.
        """
        applied = self.last_applied(lock)
        if applied is None:
            return None
        return RenderLive(
            outputs_present={
                scene: _render_path(ctx.workspace, listing, scene).is_file()
                for scene in applied.scenes
            }
        )

    def plan(
        self, desired: RenderDesired, applied: RenderApplied | None, live: RenderLive | None
    ) -> StagePlan:
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
        return StagePlan(stage=self.name, will_run=False)

    def _will_run(
        self, desired: RenderDesired, reason: str, *, missing: tuple[str, ...]
    ) -> StagePlan:
        return StagePlan(
            stage=self.name,
            will_run=True,
            reason=reason,
            actions=self._actions(desired, missing),
        )

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

    def apply(
        self, ctx: RunContext, stage_plan: StagePlan, desired: RenderDesired
    ) -> StageApplyResult:
        """A flat loop over already-resolved work.

        Nothing here re-opens ``template.yaml``, re-resolves an artwork or
        re-derives a path: every one of those answers came from ``desired()``,
        which is the same object that produced ``input_hash``. That is what
        makes "what was hashed is what was rendered" true by construction
        rather than by two branch sets agreeing.
        """
        workspace = ctx.workspace
        design_cache: dict[Path, RGBA] = {}
        map_caches: dict[str, DerivedMapCache] = {}
        outputs: dict[str, str] = {}

        for work in desired.works:
            base = load_template_base(work.base_image)
            map_cache = map_caches.setdefault(
                work.template, DerivedMapCache(workspace.template_derived_dir(work.template))
            )
            height = map_cache.height(work.map_key, base) if work.wants_height else None
            luminance = map_cache.luminance(work.map_key, base) if work.wants_luminance else None

            layers = []
            for layer in work.layers:
                if layer.design not in design_cache:
                    design_cache[layer.design] = load_design(layer.design)
                layers.append(Layer(design=design_cache[layer.design], cfg=layer.cfg))

            image = render_scene(base, layers, height=height, luminance=luminance)
            save_png(image, work.output)
            outputs[desired.relative(work.output)] = _hash_path(work.output)

            swatches: tuple[Swatch, ...] = tuple(
                sample_swatch(base, layer.cfg.bounding_box) for layer in work.layers
            )
            ctx.emit(f"rendered {work.key}", swatches=swatches)

        applied = {
            "input_hash": self._input_hash(desired),
            "scene_config": {work.key: work.recipe() for work in desired.works},
            "scenes": list(desired.scenes),
        }
        return StageApplyResult(applied=applied, outputs=outputs)

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

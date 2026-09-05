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
"""

from __future__ import annotations

import hashlib
import json
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
    MultipleTemplate,
    SingleTemplate,
)
from etsy_listings.render.io import load_design, load_template_base, save_png
from etsy_listings.render.maps import DerivedMapCache
from etsy_listings.render.pipeline import Layer, render_scene
from etsy_listings.render.pipeline import render as render_pipeline
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
class RenderDesired:
    listing: str
    scenes: tuple[str, ...]  # scene keys, first-seen media order, deduped
    design_hash: dict[str, str]  # artwork key -> sha256, only keys actually used
    template_hash: dict[str, str]  # template name -> sha256
    scene_config: dict[str, str]  # scene key -> canonical json of its render recipe
    scene_inputs: dict[str, tuple[str, ...]]  # scene key -> the files it reads
    scene_outputs: dict[str, str]  # scene key -> the file it writes


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


class RenderStage:
    name = "render"
    local = True

    def desired(self, ctx: RunContext, listing: str) -> RenderDesired:
        workspace = ctx.workspace
        listing_cfg = workspace.load_listing(listing)
        profile = workspace.load_profile(listing_cfg.profile)

        def relative(path: Path) -> str:
            return to_workspace_relative_posix(workspace.root, path)

        design_paths: dict[str, Path] = {
            key: workspace.resolve(ref, relative_to=workspace.listing_dir(listing))
            for key, ref in listing_cfg.design.items()
        }

        referenced: dict[tuple[str, str | None], None] = {}
        for entry in listing_cfg.media:
            if isinstance(entry, TemplateMediaEntry):
                referenced.setdefault((entry.template, entry.colour), None)

        template_texts: dict[str, str] = {}
        template_configs: dict[str, AnyTemplate] = {}
        template_hash: dict[str, str] = {}
        design_hash: dict[str, str] = {}
        scenes: list[str] = []
        scene_config: dict[str, str] = {}
        scene_inputs: dict[str, tuple[str, ...]] = {}
        scene_outputs: dict[str, str] = {}

        for template_name, colour in referenced:
            if template_name not in template_configs:
                config_path = workspace.template_config_file(template_name)
                if not config_path.is_file():
                    raise TemplateNotFoundError(template_name, config_path)
                # The verbatim text is kept alongside the parsed config: it is
                # what feeds template_hash, and re-serialising the model would
                # hash a normalised form rather than the file on disk.
                template_texts[template_name] = config_path.read_text(encoding="utf-8")
                template_configs[template_name] = workspace.load_template_config(template_name)

            template_cfg = template_configs[template_name]
            kind = template_cfg.kind
            if (kind == "colour-matrix") != (colour is not None):
                raise MediaColourMismatchError(template_name, kind, colour)

            scene = _scene_key(template_name, colour)
            scenes.append(scene)
            config_path = workspace.template_config_file(template_name)
            scene_outputs[scene] = relative(workspace.render_file(listing, template_name, colour))

            if isinstance(template_cfg, ColourMatrixTemplate):
                assert colour is not None
                base_path = workspace.template_base_image(template_name, colour)
                if not base_path.is_file():
                    raise TemplateAssetError(template_name, colour, base_path)
                artwork_key = _resolve_artwork(
                    colour=colour, listing=listing_cfg, profile=profile, template_override=None
                )
                design_hash[artwork_key] = _hash_path(design_paths[artwork_key])
                cfg = template_cfg.render_config()
                scene_config[scene] = json.dumps(
                    {
                        "template": template_name,
                        "kind": kind,
                        "artwork": artwork_key,
                        "render_config": cfg.canonical_json(),
                    },
                    sort_keys=True,
                )
                scene_inputs[scene] = (
                    relative(design_paths[artwork_key]),
                    relative(config_path),
                    relative(base_path),
                )
                template_hash.setdefault(
                    template_name,
                    _hash_bytes(
                        template_texts[template_name].encode("utf-8") + base_path.read_bytes()
                    ),
                )

            elif isinstance(template_cfg, SingleTemplate):
                base_path = workspace.template_scene_image(template_name)
                if not base_path.is_file():
                    raise TemplateAssetError(template_name, None, base_path)
                artwork_key = _resolve_artwork(
                    colour=template_cfg.colour,
                    listing=listing_cfg,
                    profile=profile,
                    template_override=template_cfg.artwork,
                )
                design_hash[artwork_key] = _hash_path(design_paths[artwork_key])
                cfg = template_cfg.render_config()
                scene_config[scene] = json.dumps(
                    {
                        "template": template_name,
                        "kind": kind,
                        "artwork": artwork_key,
                        "render_config": cfg.canonical_json(),
                    },
                    sort_keys=True,
                )
                scene_inputs[scene] = (
                    relative(design_paths[artwork_key]),
                    relative(config_path),
                    relative(base_path),
                )
                template_hash[template_name] = _hash_bytes(
                    template_texts[template_name].encode("utf-8") + base_path.read_bytes()
                )

            else:
                assert isinstance(template_cfg, MultipleTemplate)
                base_path = workspace.template_scene_image(template_name)
                if not base_path.is_file():
                    raise TemplateAssetError(template_name, None, base_path)
                placement_entries = []
                artwork_refs: dict[str, None] = {}
                for placement in template_cfg.placements:
                    artwork_key = _resolve_artwork(
                        colour=placement.colour,
                        listing=listing_cfg,
                        profile=profile,
                        template_override=placement.artwork,
                    )
                    design_hash[artwork_key] = _hash_path(design_paths[artwork_key])
                    artwork_refs.setdefault(relative(design_paths[artwork_key]), None)
                    p_cfg = template_cfg.render_config_for(placement)
                    placement_entries.append(
                        {
                            "colour": placement.colour,
                            "artwork": artwork_key,
                            "render_config": p_cfg.canonical_json(),
                        }
                    )
                scene_config[scene] = json.dumps(
                    {
                        "template": template_name,
                        "kind": kind,
                        "colour_coverage": template_cfg.colour_coverage,
                        "placements": placement_entries,
                    },
                    sort_keys=True,
                )
                scene_inputs[scene] = (*artwork_refs, relative(config_path), relative(base_path))
                template_hash[template_name] = _hash_bytes(
                    template_texts[template_name].encode("utf-8") + base_path.read_bytes()
                )

        return RenderDesired(
            listing=listing,
            scenes=tuple(scenes),
            design_hash=design_hash,
            template_hash=template_hash,
            scene_config=scene_config,
            scene_inputs=scene_inputs,
            scene_outputs=scene_outputs,
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
        return tuple(
            Action(
                description=f"render {scene}",
                inputs=desired.scene_inputs[scene],
                outputs=(desired.scene_outputs[scene],),
                missing_outputs=(desired.scene_outputs[scene],) if scene in missing_set else (),
            )
            for scene in desired.scenes
        )

    def apply(
        self, ctx: RunContext, stage_plan: StagePlan, desired: RenderDesired
    ) -> StageApplyResult:
        workspace = ctx.workspace
        listing_cfg = workspace.load_listing(desired.listing)
        profile = workspace.load_profile(listing_cfg.profile)

        design_cache: dict[str, RGBA] = {}

        def design_for(artwork_key: str) -> RGBA:
            if artwork_key not in design_cache:
                ref = listing_cfg.design[artwork_key]
                path = workspace.resolve(ref, relative_to=workspace.listing_dir(desired.listing))
                design_cache[artwork_key] = load_design(path)
            return design_cache[artwork_key]

        template_configs: dict[str, AnyTemplate] = {}
        map_caches: dict[str, DerivedMapCache] = {}
        outputs: dict[str, str] = {}

        for scene in desired.scenes:
            template_name, colour = _split_scene_key(scene)

            if template_name not in template_configs:
                template_configs[template_name] = workspace.load_template_config(template_name)
                map_caches[template_name] = DerivedMapCache(
                    workspace.template_derived_dir(template_name)
                )

            template_cfg = template_configs[template_name]
            map_cache = map_caches[template_name]
            swatches: tuple[Swatch, ...]

            if isinstance(template_cfg, ColourMatrixTemplate):
                assert colour is not None
                base = load_template_base(workspace.template_base_image(template_name, colour))
                cfg = template_cfg.render_config()
                artwork_key = _resolve_artwork(
                    colour=colour, listing=listing_cfg, profile=profile, template_override=None
                )
                height = map_cache.height(colour, base) if cfg.displace.enabled else None
                luminance = map_cache.luminance(colour, base) if cfg.shade.enabled else None
                swatches = (sample_swatch(base, cfg.bounding_box),)
                image = render_pipeline(
                    design_for(artwork_key), base, cfg, height=height, luminance=luminance
                )
                output_path = workspace.render_file(desired.listing, template_name, colour)

            elif isinstance(template_cfg, SingleTemplate):
                base = load_template_base(workspace.template_scene_image(template_name))
                cfg = template_cfg.render_config()
                artwork_key = _resolve_artwork(
                    colour=template_cfg.colour,
                    listing=listing_cfg,
                    profile=profile,
                    template_override=template_cfg.artwork,
                )
                height = map_cache.height(template_name, base) if cfg.displace.enabled else None
                luminance = map_cache.luminance(template_name, base) if cfg.shade.enabled else None
                swatches = (sample_swatch(base, cfg.bounding_box),)
                image = render_pipeline(
                    design_for(artwork_key), base, cfg, height=height, luminance=luminance
                )
                output_path = workspace.render_file(desired.listing, template_name)

            else:
                assert isinstance(template_cfg, MultipleTemplate)
                base = load_template_base(workspace.template_scene_image(template_name))
                layers = []
                for placement in template_cfg.placements:
                    artwork_key = _resolve_artwork(
                        colour=placement.colour,
                        listing=listing_cfg,
                        profile=profile,
                        template_override=placement.artwork,
                    )
                    layers.append(
                        Layer(
                            design=design_for(artwork_key),
                            cfg=template_cfg.render_config_for(placement),
                        )
                    )
                height = (
                    map_cache.height(template_name, base) if template_cfg.displace.enabled else None
                )
                luminance = (
                    map_cache.luminance(template_name, base) if template_cfg.shade.enabled else None
                )
                swatches = tuple(
                    sample_swatch(base, placement.bounding_box)
                    for placement in template_cfg.placements
                )
                image = render_scene(base, layers, height=height, luminance=luminance)
                output_path = workspace.render_file(desired.listing, template_name)

            save_png(image, output_path)
            output_hash = _hash_path(output_path)
            outputs[to_workspace_relative_posix(workspace.root, output_path)] = output_hash
            ctx.emit(f"rendered {scene}", swatches=swatches)

        applied = {
            "input_hash": self._input_hash(desired),
            "scene_config": desired.scene_config,
            "scenes": list(desired.scenes),
        }
        return StageApplyResult(applied=applied, outputs=outputs)

    @staticmethod
    def _input_hash(desired: RenderDesired) -> str:
        payload = {
            "design_hash": desired.design_hash,
            "template_hash": desired.template_hash,
            "scene_config": desired.scene_config,
        }
        return canonical_hash(payload)

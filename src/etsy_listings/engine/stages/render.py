"""The ``render`` stage: local-only (no live remote state), wires the pure
render pipeline into plan/apply.

Its ``desired()`` does the I/O the render *passes* deliberately don't (A7):
loading the listing/profile/template config and hashing the design + template
assets. ``apply()`` is the one place renders actually happen and get written
to ``.cache/renders/{listing}/{template}/...`` (PRD: rendered mockups persist
in the gitignored cache, keyed by listing, never committed; namespaced by
template since a listing can reference several -- see
``Workspace.render_file``).

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

import yaml

from etsy_listings.config.listing import Listing, TemplateMediaEntry
from etsy_listings.config.profile import Profile
from etsy_listings.engine.change import StagePlan
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile, canonical_hash, to_workspace_relative_posix
from etsy_listings.engine.stage import StageApplyResult
from etsy_listings.render.config import (
    ColourMatrixTemplate,
    MultipleTemplate,
    SingleTemplate,
    load_template_config,
)
from etsy_listings.render.io import load_design, load_template_base, save_png
from etsy_listings.render.maps import DerivedMapCache
from etsy_listings.render.pipeline import Layer, render_scene
from etsy_listings.render.pipeline import render as render_pipeline
from etsy_listings.render.types import RGBA

TemplateConfigT = ColourMatrixTemplate | MultipleTemplate | SingleTemplate


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
    def __init__(self, colour: str | None, tone: str | None, available: list[str]) -> None:
        detail = f"colour {colour!r}" if colour is not None else "this template"
        tone_note = f" (tone: {tone})" if tone else ""
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
    if colour is not None and colour in listing.artwork:
        candidate = listing.artwork[colour]
    elif template_override is not None:
        candidate = template_override
    elif colour is not None and colour in profile.colour_tone:
        toned = f"on-{profile.colour_tone[colour]}"
        candidate = toned if toned in key_set else None

    if candidate is None and len(keys) == 1:
        candidate = keys[0]

    if candidate is None or candidate not in key_set:
        tone = profile.colour_tone.get(colour) if colour is not None else None
        raise ArtworkResolutionError(colour, tone, sorted(keys))
    return candidate


@dataclass(frozen=True)
class RenderDesired:
    listing: str
    scenes: tuple[str, ...]  # scene keys, first-seen media order, deduped
    design_hash: dict[str, str]  # artwork key -> sha256, only keys actually used
    template_hash: dict[str, str]  # template name -> sha256
    scene_config: dict[str, str]  # scene key -> canonical json of its render recipe


@dataclass(frozen=True)
class RenderApplied:
    input_hash: str
    scenes: tuple[str, ...]


def _scene_key(template: str, colour: str | None) -> str:
    return f"{template}/{colour}" if colour is not None else template


def _split_scene_key(scene: str) -> tuple[str, str | None]:
    if "/" in scene:
        template, colour = scene.split("/", 1)
        return template, colour
    return scene, None


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

        design_paths: dict[str, Path] = {
            key: workspace.resolve(ref, relative_to=workspace.listing_dir(listing))
            for key, ref in listing_cfg.design.items()
        }

        referenced: dict[tuple[str, str | None], None] = {}
        for entry in listing_cfg.media:
            if isinstance(entry, TemplateMediaEntry):
                referenced.setdefault((entry.template, entry.colour), None)

        template_texts: dict[str, str] = {}
        template_configs: dict[str, TemplateConfigT] = {}
        template_hash: dict[str, str] = {}
        design_hash: dict[str, str] = {}
        scenes: list[str] = []
        scene_config: dict[str, str] = {}

        for template_name, colour in referenced:
            if template_name not in template_configs:
                config_path = workspace.template_config_file(template_name)
                if not config_path.is_file():
                    raise TemplateNotFoundError(template_name, config_path)
                text = config_path.read_text(encoding="utf-8")
                template_texts[template_name] = text
                template_configs[template_name] = load_template_config(yaml.safe_load(text))

            template_cfg = template_configs[template_name]
            kind = template_cfg.kind
            if (kind == "colour-matrix") != (colour is not None):
                raise MediaColourMismatchError(template_name, kind, colour)

            scene = _scene_key(template_name, colour)
            scenes.append(scene)

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
                template_hash[template_name] = _hash_bytes(
                    template_texts[template_name].encode("utf-8") + base_path.read_bytes()
                )

            else:
                assert isinstance(template_cfg, MultipleTemplate)
                base_path = workspace.template_scene_image(template_name)
                if not base_path.is_file():
                    raise TemplateAssetError(template_name, None, base_path)
                placement_entries = []
                for placement in template_cfg.placements:
                    artwork_key = _resolve_artwork(
                        colour=placement.colour,
                        listing=listing_cfg,
                        profile=profile,
                        template_override=placement.artwork,
                    )
                    design_hash[artwork_key] = _hash_path(design_paths[artwork_key])
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
                template_hash[template_name] = _hash_bytes(
                    template_texts[template_name].encode("utf-8") + base_path.read_bytes()
                )

        return RenderDesired(
            listing=listing,
            scenes=tuple(scenes),
            design_hash=design_hash,
            template_hash=template_hash,
            scene_config=scene_config,
        )

    def last_applied(self, lock: Lockfile) -> RenderApplied | None:
        data = lock.applied.get(self.name)
        if data is None:
            return None
        return RenderApplied(input_hash=data["input_hash"], scenes=tuple(data["scenes"]))

    def read_live(self, ctx: RunContext, lock: Lockfile) -> None:
        return None

    def plan(self, desired: RenderDesired, applied: RenderApplied | None, live: None) -> StagePlan:
        input_hash = self._input_hash(desired)
        if applied is None:
            return StagePlan(stage=self.name, will_run=True, reason="no previous render")
        if applied.input_hash != input_hash:
            return StagePlan(stage=self.name, will_run=True, reason="design or template changed")
        if applied.scenes != desired.scenes:
            return StagePlan(stage=self.name, will_run=True, reason="referenced scenes changed")
        return StagePlan(stage=self.name, will_run=False)

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

        template_configs: dict[str, TemplateConfigT] = {}
        map_caches: dict[str, DerivedMapCache] = {}
        outputs: dict[str, str] = {}

        for scene in desired.scenes:
            template_name, colour = _split_scene_key(scene)

            if template_name not in template_configs:
                text = workspace.template_config_file(template_name).read_text(encoding="utf-8")
                template_configs[template_name] = load_template_config(yaml.safe_load(text))
                map_caches[template_name] = DerivedMapCache(
                    workspace.template_derived_dir(template_name)
                )

            template_cfg = template_configs[template_name]
            map_cache = map_caches[template_name]

            if isinstance(template_cfg, ColourMatrixTemplate):
                assert colour is not None
                base = load_template_base(workspace.template_base_image(template_name, colour))
                cfg = template_cfg.render_config()
                artwork_key = _resolve_artwork(
                    colour=colour, listing=listing_cfg, profile=profile, template_override=None
                )
                height = map_cache.height(colour, base) if cfg.displace.enabled else None
                luminance = map_cache.luminance(colour, base) if cfg.shade.enabled else None
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
                image = render_scene(base, layers, height=height, luminance=luminance)
                output_path = workspace.render_file(desired.listing, template_name)

            save_png(image, output_path)
            output_hash = _hash_path(output_path)
            outputs[to_workspace_relative_posix(workspace.root, output_path)] = output_hash
            ctx.emit(f"rendered {scene}")

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

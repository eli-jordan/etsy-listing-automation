"""The ``render`` stage: local-only (no live remote state), wires the pure
render pipeline into plan/apply.

Its ``desired()`` does the I/O the render *passes* deliberately don't (A7):
loading the listing/profile/template config and hashing the design + template
assets. ``apply()`` is the one place renders actually happen and get written
to ``.cache/renders/{listing}/{colour}.png`` (PRD: rendered mockups persist in
the gitignored cache, keyed by listing, never committed).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import yaml

from etsy_listings.config.listing import Listing
from etsy_listings.config.profile import Profile
from etsy_listings.engine.change import StagePlan
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile, canonical_hash, to_workspace_relative_posix
from etsy_listings.engine.stage import StageApplyResult
from etsy_listings.render.config import TemplateConfig
from etsy_listings.render.io import load_design, load_template_base, save_png
from etsy_listings.render.maps import DerivedMapCache
from etsy_listings.render.pipeline import render as render_pipeline


class TemplateAssetError(FileNotFoundError):
    def __init__(self, colour: str, path: object) -> None:
        super().__init__(f"no mockup base image for colour {colour!r} at {path}")


@dataclass(frozen=True)
class RenderDesired:
    listing: str
    design_ref: str  # workspace-relative, forward-slashed
    design_hash: str
    template_name: str
    template_hash: str
    colours: tuple[str, ...]
    configs: dict[str, str]  # colour -> RenderConfig.canonical_json()


@dataclass(frozen=True)
class RenderApplied:
    input_hash: str
    colours: tuple[str, ...]


class RenderStage:
    name = "render"
    local = True

    def desired(self, ctx: RunContext, listing: str) -> RenderDesired:
        root = ctx.workspace.root
        listing_dir = root / "listings" / listing
        listing_cfg = Listing.load(
            listing_dir / "listing.yaml", currency=ctx.workspace.defaults.currency
        )
        profile = Profile.load(root / "profiles" / f"{listing_cfg.profile}.yaml")

        design_path = ctx.workspace.resolve(listing_cfg.design, relative_to=listing_dir)
        design_hash = f"sha256:{hashlib.sha256(design_path.read_bytes()).hexdigest()}"

        template_dir = root / "mockup-templates" / profile.mockup_template
        template_yaml_text = (template_dir / "template.yaml").read_text(encoding="utf-8")
        template_config = TemplateConfig.model_validate(yaml.safe_load(template_yaml_text))

        hasher = hashlib.sha256()
        hasher.update(template_yaml_text.encode("utf-8"))
        configs: dict[str, str] = {}
        for colour in listing_cfg.colors:
            base_path = template_dir / f"{colour}.png"
            if not base_path.is_file():
                raise TemplateAssetError(colour, base_path)
            hasher.update(base_path.read_bytes())
            configs[colour] = template_config.resolve(colour).canonical_json()

        return RenderDesired(
            listing=listing,
            design_ref=to_workspace_relative_posix(root, design_path),
            design_hash=design_hash,
            template_name=profile.mockup_template,
            template_hash=f"sha256:{hasher.hexdigest()}",
            colours=tuple(listing_cfg.colors),
            configs=configs,
        )

    def last_applied(self, lock: Lockfile) -> RenderApplied | None:
        data = lock.applied.get(self.name)
        if data is None:
            return None
        return RenderApplied(input_hash=data["input_hash"], colours=tuple(data["colors"]))

    def read_live(self, ctx: RunContext, lock: Lockfile) -> None:
        return None

    def plan(self, desired: RenderDesired, applied: RenderApplied | None, live: None) -> StagePlan:
        input_hash = self._input_hash(desired)
        if applied is None:
            return StagePlan(stage=self.name, will_run=True, reason="no previous render")
        if applied.input_hash != input_hash:
            return StagePlan(stage=self.name, will_run=True, reason="design or template changed")
        if applied.colours != desired.colours:
            return StagePlan(stage=self.name, will_run=True, reason="colour list changed")
        return StagePlan(stage=self.name, will_run=False)

    def apply(
        self, ctx: RunContext, stage_plan: StagePlan, desired: RenderDesired
    ) -> StageApplyResult:
        root = ctx.workspace.root
        design_path = root / desired.design_ref
        design = load_design(design_path)

        template_dir = root / "mockup-templates" / desired.template_name
        template_config = TemplateConfig.model_validate(
            yaml.safe_load((template_dir / "template.yaml").read_text(encoding="utf-8"))
        )
        map_cache = DerivedMapCache(template_dir / "_derived")

        outputs: dict[str, str] = {}
        for colour in desired.colours:
            base_path = template_dir / f"{colour}.png"
            base = load_template_base(base_path)
            cfg = template_config.resolve(colour)

            height = map_cache.height(colour, base) if cfg.displace.enabled else None
            luminance = map_cache.luminance(colour, base) if cfg.shade.enabled else None

            image = render_pipeline(design, base, cfg, height=height, luminance=luminance)
            output_path = ctx.workspace.cache("renders", desired.listing, f"{colour}.png")
            save_png(image, output_path)

            output_hash = f"sha256:{hashlib.sha256(output_path.read_bytes()).hexdigest()}"
            outputs[to_workspace_relative_posix(root, output_path)] = output_hash
            ctx.emit(f"rendered {colour}")

        applied = {
            "input_hash": self._input_hash(desired),
            "config": desired.configs,
            "colors": list(desired.colours),
        }
        return StageApplyResult(applied=applied, outputs=outputs)

    @staticmethod
    def _input_hash(desired: RenderDesired) -> str:
        payload = {
            "design_hash": desired.design_hash,
            "template_hash": desired.template_hash,
            "configs": desired.configs,
        }
        return canonical_hash(payload)

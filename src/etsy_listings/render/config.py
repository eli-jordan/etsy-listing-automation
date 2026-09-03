"""Frozen render configuration. A7: canonical JSON of ``RenderConfig`` is what
gets hashed into the lockfile's render stage entry, so every field here must be
something that can differ between two "the same design" runs -- no derived
values, no file paths (those are workspace-relative strings elsewhere, hashed
separately as part of the render stage's desired state).
"""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator

Point = tuple[float, float]
Quad = tuple[Point, Point, Point, Point]
"""Four corners of the print area on the template image, in pixel space,
ordered top-left, top-right, bottom-right, bottom-left (PRD: homography to a
quad, not x/y/w/h, so angled and draped photos are representable)."""


class WarpConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    quad: Quad

    @model_validator(mode="after")
    def _validate_quad_is_non_degenerate(self) -> WarpConfig:
        xs = [p[0] for p in self.quad]
        ys = [p[1] for p in self.quad]
        if max(xs) - min(xs) < 1 or max(ys) - min(ys) < 1:
            raise ValueError("warp quad is degenerate (zero width or height)")
        return self


class DisplaceConfig(BaseModel):
    """PRD: implemented but off by default -- over-strong displacement looks
    melted, so it's tuned per template in the calibrator's live preview."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = False
    strength: float = 0.0  # 0..1, calibrated per template


class ShadeConfig(BaseModel):
    """PRD: on by default. ``multiply`` crushes prints on dark garments, so
    ``soft-light`` or a mid-grey pivot is used for those instead."""

    model_config = ConfigDict(frozen=True)

    enabled: bool = True
    opacity: float = 0.6  # 0..1
    blend: Literal["multiply", "soft-light", "grey-pivot"] = "soft-light"


class RenderConfig(BaseModel):
    """The resolved, per-(template, colour) configuration a single render call
    consumes. Frozen and hashable via :meth:`canonical_json`."""

    model_config = ConfigDict(frozen=True)

    warp: WarpConfig
    displace: DisplaceConfig = DisplaceConfig()
    shade: ShadeConfig = ShadeConfig()

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))


class ColourOverride(BaseModel):
    """PRD 6d: colour variants are usually the same photograph recoloured, so
    per-file overrides are the exception, not the rule."""

    model_config = ConfigDict(frozen=True)

    warp: WarpConfig | None = None


class TemplateConfig(BaseModel):
    """``mockup-templates/{name}/template.yaml``, written by the calibrator."""

    model_config = ConfigDict(frozen=True)

    warp: WarpConfig
    displace: DisplaceConfig = DisplaceConfig()
    shade: ShadeConfig = ShadeConfig()
    overrides: dict[str, ColourOverride] = {}

    def resolve(self, colour: str) -> RenderConfig:
        override = self.overrides.get(colour)
        warp = override.warp if override is not None and override.warp is not None else self.warp
        return RenderConfig(warp=warp, displace=self.displace, shade=self.shade)

"""API request/response shapes. Kept separate from :mod:`etsy_listings.render.config`
even though several fields mirror it 1:1 -- the wire schema and the render
engine's internal config are allowed to diverge (e.g. the API adds `colour`,
`design`), and coupling them would make an engine-side refactor an API break.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from etsy_listings.render.config import DisplaceConfig, ShadeConfig, WarpConfig


class TemplateSummary(BaseModel):
    name: str
    colours: list[str]
    has_config: bool


class TemplateConfigResponse(BaseModel):
    warp: WarpConfig
    displace: DisplaceConfig
    shade: ShadeConfig


class TemplateConfigUpdate(BaseModel):
    warp: WarpConfig
    displace: DisplaceConfig = DisplaceConfig()
    shade: ShadeConfig = ShadeConfig()


class PreviewRequest(BaseModel):
    colour: str
    warp: WarpConfig
    displace: DisplaceConfig = DisplaceConfig()
    shade: ShadeConfig = ShadeConfig()
    design: Literal["bundled-grid"] = "bundled-grid"
    """v1 only offers the bundled grid target -- PRD's "upload your own test
    design at any point" is a straightforward follow-up (another multipart
    endpoint) but isn't exercised by anything else in Phase 1, so it's left out
    until a real calibration workflow asks for it."""


class UploadResponse(BaseModel):
    name: str
    colours: list[str]

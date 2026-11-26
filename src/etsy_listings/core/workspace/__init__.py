"""The user's data tree, and the only code that knows its layout.

Withheld, and imported from their own modules: ``template_state``,
``listing_documents``, ``locks``, ``atomic``, and ``calibration``'s
``CalibrationStore`` and edit models."""

from etsy_listings.core.workspace import layout
from etsy_listings.core.workspace.facts import WorkspaceFacts, template_info
from etsy_listings.core.workspace.userpath import to_native_path
from etsy_listings.core.workspace.video import probe_video
from etsy_listings.core.workspace.workspace import (
    AmbiguousColourSuffixError,
    DescriptionResolution,
    InvalidNameError,
    InvalidRefError,
    MaskSource,
    PathEscapesWorkspaceError,
    ScenePhoto,
    Workspace,
    WorkspaceNotFoundError,
)

__all__ = [
    "AmbiguousColourSuffixError",
    "DescriptionResolution",
    "InvalidNameError",
    "InvalidRefError",
    "MaskSource",
    "PathEscapesWorkspaceError",
    "ScenePhoto",
    "Workspace",
    "WorkspaceFacts",
    "WorkspaceNotFoundError",
    "layout",
    "probe_video",
    "template_info",
    "to_native_path",
]

"""`listing_templates.check`: a listing template's issues with its files read."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from etsy_listings.core.config.listing_template import ListingTemplate
from etsy_listings.core.listing_templates.check import template_issues
from etsy_listings.core.workspace.facts import WorkspaceFacts
from etsy_listings.core.workspace.workspace import Workspace

VIDEO = Path(__file__).parents[2] / "fixtures" / "video" / "valid-3s-512.mp4"


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    return Workspace.discover(root_override=workspace_root)


def _template(*media: str) -> ListingTemplate:
    return ListingTemplate.model_validate(
        {
            "garment_profile": "comfort-colors-1717",
            "colors": ["black"],
            "prices": {"S": "349 NOK"},
            "media": [{"template": "flat-lay-01", "colour": "black"}, *media],
        },
        context={"currency": "NOK"},
    )


def _video_issues(workspace: Workspace, template: ListingTemplate) -> list[str]:
    issues = template_issues(
        workspace, "heavy-tee", template, facts=WorkspaceFacts.gather(workspace)
    )
    return [issue.message for issue in issues if issue.where.startswith("Listing Images › ")]


def test_a_video_ref_that_will_not_resolve_is_an_unusable_video_not_an_exception(
    workspace: Workspace,
) -> None:
    [message] = _video_issues(workspace, _template("../outside.mp4"))

    assert message.startswith("../outside.mp4 cannot be used:")


def test_a_dot_ref_is_read_beneath_the_listing_templates_directory(
    workspace: Workspace,
) -> None:
    clip = workspace.listing_template_dir("heavy-tee") / "assets" / "clip.mp4"
    clip.parent.mkdir(parents=True)
    shutil.copyfile(VIDEO, clip)

    assert _video_issues(workspace, _template("./assets/clip.mp4")) == []

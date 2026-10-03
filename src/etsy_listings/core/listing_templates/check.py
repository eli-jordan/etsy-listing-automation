"""A listing template's completeness, with its inputs read off the workspace
.

`config/listing_validation.check_listing_template` is pure, as
`check_listing` is; somebody has to resolve its description ref and probe its
videos first. For a listing that is `core/application/listing_reads.py`'s
``_business_issues``;
for a listing template it is this, and the one thing that varies is where a
ref points -- beneath the template's directory once it is saved, at the
files it will copy while it is still a draft.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from etsy_listings.core.config.description import DescriptionConfig
from etsy_listings.core.config.listing_template import ListingTemplate
from etsy_listings.core.config.listing_validation import Issue, check_listing_template
from etsy_listings.core.config.media import ProbeFailure, VideoFacts, media_kind
from etsy_listings.core.workspace.facts import WorkspaceFacts
from etsy_listings.core.workspace.workspace import InvalidRefError, Workspace


def check_listing_template_files(
    workspace: Workspace,
    template: ListingTemplate,
    *,
    resolve: Callable[[str], Path],
    facts: WorkspaceFacts,
) -> list[Issue]:
    """Every issue with ``template``, its refs resolved through ``resolve``.
    A ref that will not resolve is a video that cannot be read, reported
    against the ref -- the same answer `WorkspaceFacts.videos` gives."""
    body = template.etsy.description
    described = workspace.resolve_description(DescriptionConfig(text=body.text, ref=body.ref))
    videos: dict[str, VideoFacts | ProbeFailure] = {}
    for entry in template.media:
        if not isinstance(entry, str) or media_kind(entry) != "video":
            continue
        try:
            videos[entry] = facts.video(resolve(entry))
        except InvalidRefError as exc:
            videos[entry] = ProbeFailure(f"cannot be used: {exc.detail}")
    return check_listing_template(
        template,
        garment_profile=facts.garment_profile(template.garment_profile),
        garment_profile_names=facts.garment_profile_names,
        templates=facts.templates,
        description_ref_error=str(described.error) if described.error is not None else None,
        videos=videos,
    )


def template_issues(
    workspace: Workspace, name: str, template: ListingTemplate, *, facts: WorkspaceFacts
) -> list[Issue]:
    """The issues ``template`` has as listing template ``name`` -- the one on
    disk, whose shared refs can have changed under it since it was saved
    complete, or a ``PUT``'s candidate, whose ``./`` refs name that
    template's directory."""

    def resolve(ref: str) -> Path:
        return workspace.resolve_template_ref(ref, template=name)

    return check_listing_template_files(workspace, template, resolve=resolve, facts=facts)

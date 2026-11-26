"""A listing template's completeness, with its description ref and videos read first."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from etsy_listings.core.config.description import DescriptionConfig
from etsy_listings.core.config.listing_template import ListingTemplate
from etsy_listings.core.config.listing_validation import CheckInputs, Issue, check_listing_template
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
        CheckInputs(
            garment_profile=facts.garment_profile(template.garment_profile),
            garment_profile_names=facts.garment_profile_names,
            templates=facts.templates,
            description_ref_error=str(described.error) if described.error is not None else None,
            videos=videos,
        ),
    )


def template_issues(
    workspace: Workspace, name: str, template: ListingTemplate, *, facts: WorkspaceFacts
) -> list[Issue]:
    def resolve(ref: str) -> Path:
        return workspace.resolve_template_ref(ref, template=name)

    return check_listing_template_files(workspace, template, resolve=resolve, facts=facts)

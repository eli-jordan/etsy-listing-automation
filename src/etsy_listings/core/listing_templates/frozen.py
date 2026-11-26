from __future__ import annotations

import shutil
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from etsy_listings.core.config.listing_template import ListingTemplate
from etsy_listings.core.config.listing_validation import Issue
from etsy_listings.core.listing_templates.check import check_listing_template_files
from etsy_listings.core.listing_templates.convert import AssetCopy, owned_refs
from etsy_listings.core.workspace import locks
from etsy_listings.core.workspace.facts import WorkspaceFacts
from etsy_listings.core.workspace.workspace import Workspace


@dataclass(frozen=True)
class FrozenListingTemplate:
    workspace: Workspace
    template: ListingTemplate
    directory: Path
    saved_at: datetime

    @classmethod
    def capture(cls, workspace: Workspace, name: str, directory: Path) -> FrozenListingTemplate:
        """Holds the template's lock for the capture only, never the design
        upload; the caller cleans ``directory`` up if staging then fails."""
        with locks.hold(workspace, "listing-template", name):
            template = workspace.load_listing_template(name)
            saved_at = datetime.fromtimestamp(
                workspace.listing_template_file(name).stat().st_mtime, tz=UTC
            )
            directory.mkdir(parents=True, exist_ok=True)
            for ref in owned_refs(template):
                source = workspace.resolve_template_ref(ref, template=name)
                target = workspace.resolve_frozen_template_ref(ref, frozen_dir=directory)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
        return cls(workspace, template, directory, saved_at)

    @classmethod
    def restore(
        cls, workspace: Workspace, document: Mapping[str, Any], directory: Path, saved_at: datetime
    ) -> FrozenListingTemplate:
        template = ListingTemplate.model_validate(
            dict(document), context={"currency": workspace.defaults.etsy.currency}
        )
        return cls(workspace, template, directory, saved_at)

    def assets(self) -> tuple[AssetCopy, ...]:
        return tuple(
            AssetCopy(
                ref=ref,
                source=self.workspace.resolve_frozen_template_ref(ref, frozen_dir=self.directory),
                source_ref=ref,
            )
            for ref in owned_refs(self.template)
        )

    def copy_to(self, directory: Path) -> FrozenListingTemplate:
        directory.mkdir(parents=True, exist_ok=True)
        for asset in self.assets():
            target = self.workspace.resolve_frozen_template_ref(asset.ref, frozen_dir=directory)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(asset.source, target)
        return replace(self, directory=directory)

    def issues(self, *, facts: WorkspaceFacts) -> list[Issue]:
        return check_listing_template_files(
            self.workspace,
            self.template,
            resolve=lambda ref: self.workspace.resolve_frozen_template_ref(
                ref, frozen_dir=self.directory
            ),
            facts=facts,
        )

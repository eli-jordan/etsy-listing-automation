"""Frozen listing-template content.

Document, owned files and saved-at time are captured together, before an
upload can outlive the template. Shared refs still resolve through Workspace
and are checked again at confirm. Batches owns durable row writes, not the
protocol for locating frozen content.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from etsy_listings.config.listing_template import ListingTemplate
from etsy_listings.config.listing_validation import Issue
from etsy_listings.listing_templates.check import check_listing_template_files
from etsy_listings.listing_templates.convert import AssetCopy, owned_refs
from etsy_listings.workspace.facts import WorkspaceFacts
from etsy_listings.workspace.workspace import Workspace

TemplateLock = Callable[[str], AbstractContextManager[object]]


def _unlocked(_: str) -> AbstractContextManager[object]:
    return nullcontext()


@dataclass(frozen=True)
class FrozenListingTemplate:
    workspace: Workspace
    template: ListingTemplate
    directory: Path
    saved_at: datetime

    @classmethod
    def capture(
        cls, workspace: Workspace, name: str, directory: Path, *, lock: TemplateLock = _unlocked
    ) -> FrozenListingTemplate:
        """Capture under the same lock as template edits, rename and delete.

        The lock covers only content capture, never the design upload.
        No record or listing is created here; the caller owns cleanup if
        receiving or saving its staging session fails.
        """
        with lock(name):
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
        """Read a staging or batch record's content, independent of its source."""
        template = ListingTemplate.model_validate(
            dict(document), context={"currency": workspace.defaults.etsy.currency}
        )
        return cls(workspace, template, directory, saved_at)

    def assets(self) -> tuple[AssetCopy, ...]:
        """Only owned content; shared refs are never copied."""
        return tuple(
            AssetCopy(
                ref=ref,
                source=self.workspace.resolve_frozen_template_ref(ref, frozen_dir=self.directory),
                source_ref=ref,
            )
            for ref in owned_refs(self.template)
        )

    def copy_to(self, directory: Path) -> FrozenListingTemplate:
        """Keep frozen assets in a batch after staging goes."""
        directory.mkdir(parents=True, exist_ok=True)
        for asset in self.assets():
            target = self.workspace.resolve_frozen_template_ref(asset.ref, frozen_dir=directory)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(asset.source, target)
        return replace(self, directory=directory)

    def issues(self, *, facts: WorkspaceFacts) -> list[Issue]:
        """Recheck current shared refs against the frozen document."""
        return check_listing_template_files(
            self.workspace,
            self.template,
            resolve=lambda ref: self.workspace.resolve_frozen_template_ref(
                ref, frozen_dir=self.directory
            ),
            facts=facts,
        )

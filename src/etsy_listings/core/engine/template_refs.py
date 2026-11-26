"""A listing's lockfile, following a mockup template to a new name: image refs
move, render hashes stay (docs/features/template-rename-20261105/spec.md,
*Deployed listings*)."""

from __future__ import annotations

from etsy_listings.core.engine.lock import Lockfile
from etsy_listings.core.engine.stages.etsy_media import renamed_media_refs
from etsy_listings.core.workspace.workspace import Workspace


def follow_template_rename(workspace: Workspace, listing: str, old: str, new: str) -> None:
    """The caller holds the listing's lock."""
    path = workspace.lock_file(listing)
    lock = Lockfile.read(path)
    if lock is None:
        return
    followed = renamed_media_refs(lock, old, new)
    if followed is not lock:
        followed.write(path)

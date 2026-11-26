"""A listing's lockfile, following a mockup template to a new name: image refs
move, render hashes stay."""

from __future__ import annotations

from etsy_listings.core.engine.lock import Lockfile
from etsy_listings.core.engine.stages.etsy_media import renamed_media_refs
from etsy_listings.core.workspace.workspace import Workspace


def follow_template_rename_locked(workspace: Workspace, listing: str, old: str, new: str) -> None:
    path = workspace.lock_file(listing)
    lock = Lockfile.read(path)
    if lock is None:
        return
    followed = renamed_media_refs(lock, old, new)
    if followed is not lock:
        followed.write(path)

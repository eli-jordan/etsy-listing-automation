"""A listing's lockfile, following a mockup template to a new name.

Etsy images are remembered by ref, and a ref spells the template's name. Left
alone, a rename would read as every image of that template being removed and
a new one added, and the next apply would upload pixel-identical copies. So
the image stage's refs move with the name. The render stage's hashes do not,
because they cover the template's name and cannot be recomputed from the
lockfile: the next apply re-renders those scenes locally, to the same bytes.
"""

from __future__ import annotations

from etsy_listings.core.engine.lock import Lockfile
from etsy_listings.core.engine.stages.etsy_media import renamed_media_refs
from etsy_listings.core.workspace.workspace import Workspace


def follow_template_rename(workspace: Workspace, listing: str, old: str, new: str) -> None:
    """Rewrite ``listing``'s lockfile for template ``old`` now being ``new``.
    The caller holds the listing's lock. Writes nothing when no ref changes."""
    path = workspace.lock_file(listing)
    lock = Lockfile.read(path)
    if lock is None:
        return
    followed = renamed_media_refs(lock, old, new)
    if followed is not lock:
        followed.write(path)

"""The user's data tree: where every file lives, and the only door to it. A8.

The workspace (``shop.yaml``, ``designs/``, ``listings/``,
``mockup-templates/``, ``.cache/``) is a directory the user owns, found by
walking up from cwd for ``shop.yaml`` -- never this repository.

Two rules make this a security boundary rather than tidiness, and both matter
because template and listing names reach here from config files *and from
URLs*: :meth:`Workspace.resolve` refuses any reference that would land outside
the root, and the layout accessors refuse any name that is not a single path
segment. Together they are why the calibrator's endpoints need no path checks
of their own.

So: ask for ``workspace.lock_file(name)``, never join
``listings/<name>/state.lock.json``. The same goes for reading -- ``load_listing``,
``load_profile``, ``load_pricing_plan``, ``load_template_config`` and
``load_exceptions`` are how the tree's files are opened, so no caller writes
its own ``yaml.safe_load`` against a path it assembled.
"""

from etsy_listings.workspace import layout
from etsy_listings.workspace.userpath import to_native_path
from etsy_listings.workspace.workspace import (
    InvalidNameError,
    PathEscapesWorkspaceError,
    ScenePhoto,
    Workspace,
    WorkspaceNotFoundError,
)

__all__ = [
    "Workspace",
    "ScenePhoto",
    # The three refusals, each naming what it refused and why.
    "WorkspaceNotFoundError",
    "PathEscapesWorkspaceError",
    "InvalidNameError",
    # Every filename and directory name in the tree, in one module.
    "layout",
    # Cygwin/Windows path translation, for user-supplied path options (--root).
    "to_native_path",
]

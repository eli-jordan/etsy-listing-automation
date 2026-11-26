"""Reading a workspace file the app under test may be replacing right now."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from etsy_listings.core.workspace.atomic import read_bytes_retrying


def read_workspace_yaml(path: Path) -> Any:  # any YAML value
    """``path``'s YAML, read as the app's own readers read it.

    The server saves a workspace file with ``os.replace``, and Windows
    refuses to *open* a file while another thread replaces it, with a bare
    ``PermissionError``. A test polling ``listing.yaml`` for the effect of a
    gesture lands on such a save now and then, so it reads through
    ``read_bytes_retrying``, the reader half of the atomic writer, which
    waits the replace out.
    """
    return yaml.safe_load(read_bytes_retrying(path).decode("utf-8"))

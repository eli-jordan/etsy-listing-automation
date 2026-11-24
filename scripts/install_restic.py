"""Install the pinned restic under a given home and print the binary's path.

CI runs this before the tests marked ``restic`` (workspace-backup plan, P3)
and exports the path as ``ETSY_LISTINGS_RESTIC_BINARY``. It goes through the
app's own installer, so the release and its SHA-256 digests are pinned in one
place, ``core/backup/binary.py``, and a mismatched download fails here.

    uv run python scripts/install_restic.py <home>
"""

from __future__ import annotations

import sys
from pathlib import Path

from etsy_listings.core.backup.binary import ResticBinaries


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: install_restic.py <home>", file=sys.stderr)
        return 2
    print(ResticBinaries(home=Path(argv[0])).install())
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

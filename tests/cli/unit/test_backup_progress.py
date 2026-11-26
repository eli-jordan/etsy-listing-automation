"""``backup restore``'s progress line (workspace-backup plan, PR 7).

restic's ``--json`` leaves out fields that are zero, so the first figures
of a restore slow enough to report them have a total but no files restored.
"""

from __future__ import annotations

from etsy_listings.cli.backup import restore_progress_line
from etsy_listings.core.backup.repository import RestoreProgress


def test_a_status_line_without_files_restored_counts_none_yet() -> None:
    figures = RestoreProgress(fraction=0.02, files_total=4100)

    assert restore_progress_line(figures) == "  2% · 0 of 4,100 files"


def test_before_restic_knows_the_total_only_the_percentage_shows() -> None:
    assert restore_progress_line(RestoreProgress(fraction=0.5)) == "  50%"

"""The ``backup:`` block of ``settings.yaml`` (workspace-backup spec,
*Configuration*; plan, PR 2 and decision P5).

An absent block means backups are off, so unlike every other section an
empty ``backup:`` is not filled in with defaults: there is no default
repository to back up to.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings.core.config.errors import ConfigLoadError
from etsy_listings.core.config.settings import BackupSettings, RetentionSettings, Settings

FULL_BLOCK = """\
backup:
  repository: C:\\Users\\Admin\\naturally-inked-studio-backups
  destinations:
    - C:\\Users\\Admin\\iCloudDrive\\naturally-inked-studio-backups
    - D:\\nas\\backups
  interval_hours: 24
  retention:
    keep_within_days: 10
    weekly: 6
    monthly: 12
  restic_binary: /usr/bin/restic
"""


def _load(tmp_path: Path, text: str) -> Settings:
    path = tmp_path / "settings.yaml"
    path.write_text(text, encoding="utf-8")
    return Settings.load(path)


@pytest.mark.parametrize(
    "text",
    ["", "batch_ai:\n  concurrency: 2\n", "backup:\n"],
    ids=["empty-file", "other-sections-only", "empty-block"],
)
def test_without_a_backup_block_backups_are_off(tmp_path: Path, text: str) -> None:
    assert _load(tmp_path, text).backup is None


def test_a_missing_file_means_backups_are_off(tmp_path: Path) -> None:
    assert Settings.load(tmp_path / "settings.yaml").backup is None


def test_a_full_block_loads_every_key(tmp_path: Path) -> None:
    backup = _load(tmp_path, FULL_BLOCK).backup

    assert backup == BackupSettings(
        repository=Path("C:\\Users\\Admin\\naturally-inked-studio-backups"),
        destinations=(
            Path("C:\\Users\\Admin\\iCloudDrive\\naturally-inked-studio-backups"),
            Path("D:\\nas\\backups"),
        ),
        interval_hours=24,
        retention=RetentionSettings(keep_within_days=10, weekly=6, monthly=12),
        restic_binary=Path("/usr/bin/restic"),
    )


def test_a_block_naming_only_the_repository_takes_the_spec_defaults(tmp_path: Path) -> None:
    backup = _load(tmp_path, "backup:\n  repository: /srv/backups\n").backup

    assert backup is not None
    assert backup.destinations == ()
    assert backup.interval_hours == 12
    assert (backup.retention.keep_within_days, backup.retention.weekly) == (7, 4)
    assert backup.retention.monthly == 3
    assert backup.restic_binary is None


def _refusal(tmp_path: Path, text: str) -> str:
    with pytest.raises(ConfigLoadError) as caught:
        _load(tmp_path, text)
    return str(caught.value)


@pytest.mark.parametrize("hours", [0, 3, 5, 8, 72, "twelve"])
def test_an_interval_the_page_does_not_offer_is_refused(tmp_path: Path, hours: object) -> None:
    message = _refusal(tmp_path, f"backup:\n  repository: /srv/b\n  interval_hours: {hours}\n")

    assert "backup.interval_hours" in message
    assert "4, 6, 12, 24 or 48" in message


@pytest.mark.parametrize("key", ["keep_within_days", "weekly", "monthly"])
@pytest.mark.parametrize("value", [0, -1])
def test_retention_below_one_is_refused(tmp_path: Path, key: str, value: int) -> None:
    message = _refusal(
        tmp_path, f"backup:\n  repository: /srv/b\n  retention:\n    {key}: {value}\n"
    )

    assert f"backup.retention.{key}" in message
    assert "greater than or equal to 1" in message


def test_a_block_without_a_repository_is_refused(tmp_path: Path) -> None:
    message = _refusal(tmp_path, "backup:\n  interval_hours: 12\n")

    assert "backup.repository" in message


def test_an_unknown_backup_key_is_refused(tmp_path: Path) -> None:
    message = _refusal(tmp_path, "backup:\n  repository: /srv/b\n  intervall_hours: 12\n")

    assert "backup.intervall_hours" in message

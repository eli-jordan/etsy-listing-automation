"""``backup-state.json`` and the run history (workspace-backup spec, *Status
and warnings*), under a ``home`` in ``tmp_path`` (plan, P2)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from etsy_listings.core.backup.state import HISTORY_FILE, BackupStateStore, RunRecord

AT = datetime(2026, 11, 23, 9, tzinfo=UTC)


def test_state_recorded_for_another_repository_is_not_reused(tmp_path: Path) -> None:
    store = BackupStateStore(tmp_path)
    store.save(store.load(tmp_path / "old").model_copy(update={"last_prune": AT}))

    assert store.load(tmp_path / "old").last_prune == AT
    assert store.load(tmp_path / "new").last_prune is None


def test_a_damaged_history_line_loses_only_itself(tmp_path: Path) -> None:
    store = BackupStateStore(tmp_path)
    first = RunRecord(repository="r", started_at=AT, finished_at=AT, outcome="succeeded")
    second = first.model_copy(update={"outcome": "failed", "message": "restic: locked"})
    store.append_run(first)
    with (store.directory / HISTORY_FILE).open("a", encoding="utf-8") as history:
        history.write('{"repository": "r", "started_at": "2026-11')
    store.append_run(second)

    assert store.runs() == [first, second]

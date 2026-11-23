"""The copy against repositories restic itself made, with every folder in
``tmp_path`` (workspace-backup plan, PR 4 and P3). Skipped unless
``ETSY_LISTINGS_RESTIC_BINARY`` names restic."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from etsy_listings.core.backup.destinations import CopyHooks, CopyStep, copy_repository
from etsy_listings.core.backup.restic import Restic

from tests.support.repository_files import files

pytestmark = pytest.mark.restic

PASSWORD = "correct horse battery staple"


class InterruptedCopyError(Exception):
    pass


def _interrupt_after(count: int) -> CopyHooks:
    seen: list[CopyStep] = []

    def observe(step: CopyStep) -> None:
        seen.append(step)
        if len(seen) == count:
            raise InterruptedCopyError

    return CopyHooks(observe=observe)


def test_a_copy_interrupted_at_any_file_still_opens_in_restic(
    restic_binary: Path, tmp_path: Path
) -> None:
    local = Restic(restic_binary, tmp_path / "backups", PASSWORD)
    local.init()
    source = tmp_path / "workspace"
    source.mkdir()
    (source / "shop.yaml").write_bytes(b"shop: naturally inked\n")
    local.run("backup", str(source), "--host", "test")
    first = tmp_path / "first-copy"
    assert copy_repository(local.repository, first).outcome == "copied"
    # A week later: a new design, the oldest snapshot forgotten and pruned,
    # so the next copy both adds files and deletes expired ones.
    (source / "fox.png").write_bytes(bytes(range(256)) * 64)
    local.run("backup", str(source), "--host", "test")
    local.run("forget", "--keep-last", "1", "--prune")
    whole = tmp_path / "whole"
    shutil.copytree(first, whole)
    every: list[CopyStep] = []
    copy_repository(local.repository, whole, hooks=CopyHooks(observe=every.append))
    steps = len(every)
    assert {step.action for step in every} == {"copied", "deleted"}

    for count in range(1, steps + 1):
        destination = tmp_path / f"interrupted-{count}"
        shutil.copytree(first, destination)
        with pytest.raises(InterruptedCopyError):
            copy_repository(local.repository, destination, hooks=_interrupt_after(count))

        copy = Restic(restic_binary, destination, PASSWORD)
        assert copy.snapshots(lock=False), f"no snapshots after {count} steps"
        copy.run("check")

        caught_up = copy_repository(local.repository, destination)
        assert caught_up.outcome == "copied"
        assert files(destination) == files(local.repository)

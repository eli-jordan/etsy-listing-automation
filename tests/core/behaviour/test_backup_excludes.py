"""The backup leaves out the app's own temporary files (workspace-backup spec,
*Backup run* step 3; plan, PR 3).

``WRITERS`` pins the exclude list to the code that makes each temporary
name: if a writer's naming changes, the source check fails and names the
writer, so the list is updated with it. The ``restic`` test then backs up a
sample of each name and proves restic leaves it out.
"""

from __future__ import annotations

from pathlib import Path

import pytest

import etsy_listings
from etsy_listings.core.application.backup_run import BackupRunner
from etsy_listings.core.backup.binary import RESTIC_BINARY_ENV_VAR, ResticBinaries
from etsy_listings.core.backup.restic import Restic, tree_path
from etsy_listings.core.workspace.workspace import Workspace

from tests.support.backups import PASSWORD, configure_backups, initialise

SOURCE = Path(etsy_listings.__file__).parent

WRITERS: dict[str, tuple[str, str]] = {
    # writer module: (the source that names its temporary, a sample name)
    "core/workspace/atomic.py": (
        'prefix=f".{path.name}.", suffix=".tmp"',
        "listings/demo/.listing.yaml.k3j2a9.tmp",
    ),
    "core/engine/stages/render.py": (
        'prefix=f".{target.name}.", suffix=".tmp"',
        "renders/demo/.main.png.q81z.tmp",
    ),
    "core/preparation/scene_cache.py": (
        'prefix=f".{path.name}.", suffix=".tmp"',
        ".cache/scenes/.forest.png.x0c1.tmp",
    ),
    "core/ai/viewable.py": (
        'f"{target.name}.{os.getpid()}.{threading.get_ident()}.tmp"',
        ".cache/ai-images/ab12/design.png.4120.9876.tmp",
    ),
    "core/clients/etsy/tokens.py": ('self._path.name + ".tmp"', "etsy-tokens.json.tmp"),
    "core/engine/lock.py": ('path.suffix + ".tmp"', "listings/demo/state.lock.json.tmp"),
    "core/preparation/distribution/src/marigold_worker/server.py": (
        '"." + destination.name + "." + uuid.uuid4().hex',
        ".cache/preparation/work/job1/.p1-normals.npz.9d0c3f7a",
    ),
    "core/preparation/position_fits.py": (
        'f".{key}-{uuid4().hex}"',
        ".cache/position-fits/.f3a9-0c1d2e/fit.npz",
    ),
    "core/application/mockup_templates.py": (
        'f".{slugs[photo]}.renaming.png"',
        "mockup-templates/tees/.forest.renaming.png",
    ),
    "core/batches/staging.py": (
        'staging_upload_file(session, "incoming")',
        ".cache/staging/s1/uploads/incoming.png",
    ),
    "core/workspace/layout.py": (
        'STAGING_ARCHIVE_FILE = "upload.zip"',
        ".cache/staging/s1/upload.zip",
    ),
    "core/preparation/artifacts.py": (
        "template_map_generation_dir(name, generation, staging=True)",
        "mockup-templates/tees/_renderer/maps/staging/g1/placement.npz",
    ),
    "core/workspace/calibration.py": (
        "template_calibration_transaction(name)",
        "mockup-templates/tees/_renderer/calibration-transaction/manifest.json",
    ),
}

KEPT = (
    ".env",
    ".cache/staging/s1/uploads/5f2b0c4e.png",
    "mockup-templates/tees/_renderer/maps/generations/g1/placement.npz",
    "mockup-templates/tees/.hidden-but-real.png",
)


@pytest.mark.parametrize("writer", sorted(WRITERS))
def test_each_writer_still_names_its_temporaries_as_the_list_expects(writer: str) -> None:
    snippet, _ = WRITERS[writer]

    assert snippet in (SOURCE / writer).read_text(encoding="utf-8"), (
        f"{writer} changed how it names its temporary files: update EXCLUDES in "
        "core/application/backup_run.py and this table together."
    )


@pytest.mark.restic
def test_the_backup_leaves_out_every_temporary_and_keeps_its_neighbours(
    restic_binary: Path, workspace_root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(RESTIC_BINARY_ENV_VAR, str(restic_binary))
    workspace = configure_backups(workspace_root, tmp_path / "backups", password=None)
    binaries = ResticBinaries(home=tmp_path / "home")
    initialise(workspace, tmp_path / "home")
    for relative in [sample for _, sample in WRITERS.values()] + list(KEPT[1:]):
        path = workspace_root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")

    record = BackupRunner(workspace, binaries, home=tmp_path / "home").run()
    stored = _snapshot_files(workspace, Restic(restic_binary, tmp_path / "backups", PASSWORD))

    assert record.outcome == "succeeded", record.message
    assert sorted(set(KEPT) - stored) == []
    assert sorted(stored & {sample for _, sample in WRITERS.values()}) == []


def _snapshot_files(workspace: Workspace, restic: Restic) -> set[str]:
    root = tree_path(str(workspace.root))
    nodes = restic.run("ls", "latest")
    return {
        node["path"].removeprefix(root + "/")
        for node in nodes
        if isinstance(node, dict) and node.get("type") == "file"
    }

from __future__ import annotations

from pathlib import Path

from etsy_listings.engine.lock import Lockfile, canonical_hash, to_workspace_relative_posix

SAMPLE_APPLIED = {
    "render": {
        "input_hash": "sha256:abc123",
        "config": {"warp": {"enabled": True}},
        "colors": ["black", "moss"],
    },
    "generate": {"title": "Take A Hike", "tags": ["hiking", "retro"]},
}


def test_canonical_hash_is_deterministic_across_runs() -> None:
    assert canonical_hash(SAMPLE_APPLIED) == canonical_hash(SAMPLE_APPLIED)


def test_canonical_hash_ignores_key_order() -> None:
    reordered = {
        "generate": {"tags": ["hiking", "retro"], "title": "Take A Hike"},
        "render": {
            "colors": ["black", "moss"],
            "config": {"warp": {"enabled": True}},
            "input_hash": "sha256:abc123",
        },
    }
    assert canonical_hash(SAMPLE_APPLIED) == canonical_hash(reordered)


def test_canonical_hash_changes_with_content() -> None:
    changed = {**SAMPLE_APPLIED, "render": {**SAMPLE_APPLIED["render"], "colors": ["black"]}}
    assert canonical_hash(SAMPLE_APPLIED) != canonical_hash(changed)


def test_two_runs_with_no_input_change_produce_byte_identical_applied_subtrees() -> None:
    """The PRD's core determinism guarantee: re-running against unchanged inputs
    must make no remote changes, which starts with the lockfile hashing
    identically run over run."""
    lock_a = Lockfile(
        tool_version="0.1.0", applied_at="2026-01-01T00:00:00Z", applied=SAMPLE_APPLIED
    )
    lock_b = Lockfile(
        tool_version="0.1.1",  # different tool version...
        applied_at="2026-06-01T00:00:00Z",  # ...and a different apply time...
        applied=SAMPLE_APPLIED,  # ...but the same applied content
    )
    assert lock_a.input_hash() == lock_b.input_hash()


def test_tool_version_and_applied_at_are_excluded_from_the_hash() -> None:
    lock = Lockfile(tool_version="0.1.0", applied_at="2026-01-01T00:00:00Z", applied=SAMPLE_APPLIED)
    assert lock.input_hash() == canonical_hash(SAMPLE_APPLIED)


def test_remote_is_excluded_from_the_hash() -> None:
    lock_a = Lockfile(tool_version="0.1.0", applied_at="t", applied=SAMPLE_APPLIED, remote={})
    lock_b = Lockfile(
        tool_version="0.1.0",
        applied_at="t",
        applied=SAMPLE_APPLIED,
        remote={"etsy_listing_id": 123456},
    )
    assert lock_a.input_hash() == lock_b.input_hash()


def test_lockfile_round_trips_through_disk(tmp_path: Path) -> None:
    path = tmp_path / "state.lock.json"
    lock = Lockfile(tool_version="0.1.0", applied_at="2026-01-01T00:00:00Z", applied=SAMPLE_APPLIED)
    lock.write(path)
    loaded = Lockfile.read(path)
    assert loaded is not None
    assert loaded.input_hash() == lock.input_hash()


def test_read_missing_lockfile_returns_none(tmp_path: Path) -> None:
    assert Lockfile.read(tmp_path / "does-not-exist.json") is None


def test_workspace_relative_posix_uses_forward_slashes(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    nested = root / "listings" / "take-a-hike" / "listing.yaml"
    nested.parent.mkdir(parents=True)
    nested.write_text("x")
    relative = to_workspace_relative_posix(root, nested)
    assert relative == "listings/take-a-hike/listing.yaml"
    assert "\\" not in relative

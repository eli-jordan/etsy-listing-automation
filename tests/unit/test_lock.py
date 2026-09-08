from __future__ import annotations

from pathlib import Path

from etsy_listings.engine.lock import (
    Lockfile,
    StageApplyResult,
    canonical_hash,
    to_workspace_relative_posix,
)

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


# ------------------------------------------------- folding a stage's result
#
# These need no stage, no context and no workspace. That is the point of the
# lockfile owning its own merge: the rules for what happens to each of the
# four axes used to be a loop in `execute`, so exercising them meant driving a
# whole apply.


def _lock(**kwargs: object) -> Lockfile:
    return Lockfile(tool_version="0.1.0", applied_at="t", **kwargs)  # type: ignore[arg-type]


def test_applied_for_returns_only_that_stages_subtree() -> None:
    lock = _lock(applied=SAMPLE_APPLIED)
    assert lock.applied_for("generate") == SAMPLE_APPLIED["generate"]


def test_applied_for_is_none_when_the_stage_has_never_run() -> None:
    assert _lock(applied=SAMPLE_APPLIED).applied_for("printify_product") is None


def test_fold_replaces_that_stages_document_rather_than_merging_into_it() -> None:
    """A stage's `applied` is a whole document. Merging would keep a field the
    stage has stopped emitting, and the lockfile would describe a state that
    was never applied."""
    lock = _lock(applied={"render": {"input_hash": "sha256:old", "scenes": ["a"]}})

    folded = lock.fold("render", StageApplyResult(applied={"input_hash": "sha256:new"}))

    assert folded.applied["render"] == {"input_hash": "sha256:new"}


def test_fold_merges_remote_so_one_stages_ids_do_not_displace_anothers() -> None:
    """A20. The Printify id arriving must not take the Etsy listing id with it."""
    lock = _lock(remote={"etsy_listing_id": 123456})

    folded = lock.fold(
        "printify_product", StageApplyResult(applied={}, remote={"printify_product_id": "abc"})
    )

    assert folded.remote == {"etsy_listing_id": 123456, "printify_product_id": "abc"}


def test_fold_merges_outputs_by_path() -> None:
    lock = _lock(outputs={"a.png": "sha256:a"})

    folded = lock.fold("render", StageApplyResult(applied={}, outputs={"b.png": "sha256:b"}))

    assert folded.outputs == {"a.png": "sha256:a", "b.png": "sha256:b"}


def test_fold_records_the_stage_once_however_often_it_runs() -> None:
    """`stages_completed` answers "has this stage ever run?", so a resumed
    apply re-folding the same stage must not grow the list."""
    lock = _lock()

    once = lock.fold("render", StageApplyResult(applied={}))
    twice = once.fold("render", StageApplyResult(applied={}))

    assert twice.stages_completed == ["render"]


def test_fold_leaves_the_original_untouched() -> None:
    """`execute` folds each stage onto the result of the last one. If fold
    mutated, a stage that failed halfway would leave the lockfile it was
    handed already carrying the changes."""
    lock = _lock(applied={"render": {"input_hash": "sha256:old"}})

    lock.fold("render", StageApplyResult(applied={"input_hash": "sha256:new"}))

    assert lock.applied == {"render": {"input_hash": "sha256:old"}}


def test_folded_remote_never_changes_the_hash() -> None:
    """The separation `remote` exists for: a product id is volatile, and
    hashing one would show a diff on every run for the rest of the listing's
    life."""
    lock = _lock(applied=SAMPLE_APPLIED)

    folded = lock.fold(
        "printify_product", StageApplyResult(applied={}, remote={"printify_product_id": "abc"})
    )
    again = folded.fold(
        "printify_product", StageApplyResult(applied={}, remote={"printify_product_id": "xyz"})
    )

    assert folded.input_hash() == again.input_hash()


def test_stamped_records_the_version_and_time_without_touching_content() -> None:
    lock = _lock(applied=SAMPLE_APPLIED)

    stamped = lock.stamped(tool_version="9.9.9", applied_at="2026-09-08T00:00:00Z")

    assert (stamped.tool_version, stamped.applied_at) == ("9.9.9", "2026-09-08T00:00:00Z")
    assert stamped.input_hash() == lock.input_hash()

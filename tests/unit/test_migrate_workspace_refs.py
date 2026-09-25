"""`scripts/migrate_workspace_refs.py` (PRD 72): the one-off rewrite of every
`listing.yaml` from listing-relative `../../` refs to two-root refs.

Driven through `main`, the way a seller runs it: what it prints and what it
leaves on disk are the whole contract.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.migrate_workspace_refs import main

LEGACY = """\
# Take a Hike -- the first listing.
garment_profile: comfort-colors-1717
design: ../../designs/take-a-hike.png   # the artwork
pricing_plan: '../../pricing-plans/launch-low.yaml'
colors: [black]
brief: "A hike."
prices: {}
etsy:
  title: ""
  description:
    lead: ""
    ref: common-copy/comfort-colors.md
  tags: []
media:
  - { template: flat-lay-01, colour: black }
  - "../../common-media/size-guide.png"
  - ../take-a-hike/close-up.png   # already beside the listing
"""

MIGRATED = """\
# Take a Hike -- the first listing.
garment_profile: comfort-colors-1717
design: designs/take-a-hike.png   # the artwork
pricing_plan: 'pricing-plans/launch-low.yaml'
colors: [black]
brief: "A hike."
prices: {}
etsy:
  title: ""
  description:
    lead: ""
    ref: common-copy/comfort-colors.md
  tags: []
media:
  - { template: flat-lay-01, colour: black }
  - "common-media/size-guide.png"
  - ./close-up.png   # already beside the listing
"""


def _write_listing(root: Path, name: str, text: str) -> Path:
    path = root / "listings" / name / "listing.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="")
    return path


@pytest.fixture
def legacy(workspace_root: Path) -> Path:
    return _write_listing(workspace_root, "take-a-hike", LEGACY)


def test_a_dry_run_prints_every_rewrite_and_changes_nothing(
    workspace_root: Path, legacy: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main([str(workspace_root)]) == 0

    out = capsys.readouterr().out
    assert "listings/take-a-hike/listing.yaml" in out
    assert "3: design: ../../designs/take-a-hike.png -> designs/take-a-hike.png" in out
    assert "4: pricing_plan: ../../pricing-plans/launch-low.yaml" in out
    assert "16: media[1]: ../../common-media/size-guide.png -> common-media/size-guide.png" in out
    assert "17: media[2]: ../take-a-hike/close-up.png -> ./close-up.png" in out
    assert "--write" in out
    assert legacy.read_text(encoding="utf-8") == LEGACY


def test_write_rewrites_the_values_and_keeps_comments_quotes_and_order(
    workspace_root: Path, legacy: Path
) -> None:
    assert main([str(workspace_root), "--write"]) == 0

    assert legacy.read_text(encoding="utf-8") == MIGRATED


def test_a_second_run_changes_nothing(
    workspace_root: Path, legacy: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    main([str(workspace_root), "--write"])
    capsys.readouterr()

    assert main([str(workspace_root), "--write"]) == 0

    assert legacy.read_text(encoding="utf-8") == MIGRATED
    assert "nothing to migrate" in capsys.readouterr().out


def test_a_workspace_with_nothing_to_migrate_is_left_byte_for_byte(
    workspace_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    fixture = workspace_root / "listings" / "take-a-hike" / "listing.yaml"
    before = fixture.read_bytes()

    assert main([str(workspace_root), "--write"]) == 0

    assert fixture.read_bytes() == before
    assert "nothing to migrate" in capsys.readouterr().out


def test_a_multi_artwork_design_map_is_rewritten_value_by_value(workspace_root: Path) -> None:
    path = _write_listing(
        workspace_root,
        "duo",
        LEGACY.replace(
            "design: ../../designs/take-a-hike.png   # the artwork\n",
            "design:\n  on-light: ../../designs/a.png\n  on-dark: ../../designs/b.png\n",
        ),
    )

    main([str(workspace_root), "--write"])

    text = path.read_text(encoding="utf-8")
    assert "  on-light: designs/a.png\n  on-dark: designs/b.png\n" in text


def test_crlf_line_endings_survive(workspace_root: Path) -> None:
    path = _write_listing(workspace_root, "take-a-hike", LEGACY.replace("\n", "\r\n"))

    main([str(workspace_root), "--write"])

    assert path.read_bytes() == MIGRATED.replace("\n", "\r\n").encode("utf-8")


def test_a_ref_that_escapes_the_workspace_is_refused_and_its_file_left_alone(
    workspace_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    text = LEGACY.replace("../../designs/take-a-hike.png", "../../../outside.png")
    path = _write_listing(workspace_root, "take-a-hike", text)

    assert main([str(workspace_root), "--write"]) == 1

    assert path.read_text(encoding="utf-8") == text
    assert "../../../outside.png" in capsys.readouterr().out


def test_a_listing_already_invalid_for_another_reason_is_migrated_with_a_note(
    workspace_root: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Validation proves the edit broke nothing: the result must validate
    exactly as well as the original. A bare-number price (PRD 24) is the
    seller's to fix, and no reason to leave the refs unreadable too."""
    text = LEGACY.replace("prices: {}", "prices: {S: 349}")
    path = _write_listing(workspace_root, "take-a-hike", text)

    assert main([str(workspace_root), "--write"]) == 0

    assert path.read_text(encoding="utf-8") == MIGRATED.replace("prices: {}", "prices: {S: 349}")
    assert "note: already invalid before migrating" in capsys.readouterr().out


def test_the_lockfile_is_not_touched(workspace_root: Path, legacy: Path) -> None:
    lock = legacy.parent / "state.lock.json"
    lock.write_text('{"applied": {"etsy_media": {"../../common-media/x.png": 1}}}\n')
    before = lock.read_bytes()

    main([str(workspace_root), "--write"])

    assert lock.read_bytes() == before

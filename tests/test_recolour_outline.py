"""The create-mockup-template-cc1717 skill's shirt outline: how `recolour.py` builds
it, what `pilot --approve` saves, and how drift and assemble read it back."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from pathlib import Path
from types import ModuleType

import cv2
import numpy as np
import pytest
from PIL import Image

SCRIPT = Path(__file__).parents[1] / ".claude/skills/create-mockup-template-cc1717/recolour.py"
SHIRT = (slice(600, 1500), slice(500, 1550))
BACKGROUND_RGB = (70, 110, 60)
SHIRT_RGB = (200, 40, 50)
PILOT_NOTE = "## Pilot review\n\nThe left sleeve stops at the wrist."


@pytest.fixture(scope="module")
def recolour() -> ModuleType:
    spec = importlib.util.spec_from_file_location("recolour", SCRIPT)
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["recolour"] = module  # dataclasses resolve their module by name
    spec.loader.exec_module(module)
    return module


def scene(shirt_rgb: tuple[int, int, int] = SHIRT_RGB) -> np.ndarray:
    """A plain shirt on a plain background, with enough grain for GrabCut's colour models."""
    rng = np.random.default_rng(7)
    pixels = np.zeros((2048, 2048, 3), np.int16)
    pixels[:] = BACKGROUND_RGB
    pixels[SHIRT] = shirt_rgb
    pixels += rng.integers(-6, 7, pixels.shape, dtype=np.int16)
    return np.clip(pixels, 0, 255).astype(np.uint8)


def write_run(
    run_dir: Path, source: np.ndarray, white: np.ndarray, black: np.ndarray, others: int = 1
) -> Path:
    for sub in ("briefs", "out"):
        (run_dir / sub).mkdir(parents=True)
    Image.fromarray(source).save(run_dir / "source.png")
    Image.fromarray(white).save(run_dir / "out" / "white.png")
    Image.fromarray(black).save(run_dir / "out" / "black.png")
    meta = {"scene": "test", "source": "x", "source_colour": None, "pilots": ["White", "Black"]}
    (run_dir / "run.json").write_text(json.dumps(meta), encoding="utf-8")
    (run_dir / "briefs" / "white.md").write_text(f"Brief\n\n{PILOT_NOTE}\n", encoding="utf-8")
    (run_dir / "briefs" / "black.md").write_text("Brief\n", encoding="utf-8")
    for slug in ("navy", "moss")[:others]:
        (run_dir / "briefs" / f"{slug}.md").write_text("Brief\n", encoding="utf-8")
    return run_dir


@pytest.fixture
def run_dir(tmp_path: Path) -> Path:
    return write_run(tmp_path / "run", scene(), scene((245, 245, 245)), scene((15, 15, 15)))


def mask_png(path: Path, size: int, box: tuple[int, int, int, int]) -> Path:
    mask = np.zeros((size, size), np.uint8)
    left, top, right, bottom = box
    mask[top:bottom, left:right] = 255
    Image.fromarray(mask).save(path)
    return path


def pilot(module: ModuleType, run_dir: Path, *, approve: bool, reference: Path | None) -> None:
    module.pilot(
        argparse.Namespace(
            run_dir=str(run_dir),
            approve=approve,
            reference=None if reference is None else reference,
        )
    )


def saved_reference(module: ModuleType, run_dir: Path) -> np.ndarray:
    with Image.open(run_dir / module.REFERENCE_MASK) as image:
        return np.asarray(image.convert("L")) > 0


def recorded_outline(run_dir: Path) -> str | None:
    return json.loads((run_dir / "run.json").read_text(encoding="utf-8")).get("outline")


def test_outline_finds_the_shirt_and_repeats_exactly(recolour: ModuleType) -> None:
    source, far, near = scene(), scene((15, 15, 15)), scene((245, 245, 245))
    first = recolour.shirt_outline(source, far, near)
    assert first is not None
    assert first.shape == (2048, 2048)
    expected = np.zeros_like(first)
    expected[SHIRT] = True
    assert (first & expected).sum() / (first | expected).sum() > 0.97
    assert np.array_equal(first, recolour.shirt_outline(source, far, near))


def test_a_pilot_that_changed_nothing_leaves_no_outline(recolour: ModuleType) -> None:
    source = scene()
    assert recolour.shirt_outline(source, source, source) is None


def test_a_seed_filling_the_frame_has_no_definite_background(recolour: ModuleType) -> None:
    source = np.full((2048, 2048, 3), 200, np.uint8)
    far = np.full((2048, 2048, 3), 10, np.uint8)
    assert recolour.shirt_outline(source, far, source) is None


def test_a_near_pilot_that_barely_differs_from_the_source_still_outlines(
    recolour: ModuleType,
) -> None:
    source = scene()
    near = np.clip(source.astype(np.int16) + 3, 0, 255).astype(np.uint8)
    outline = recolour.shirt_outline(source, scene((15, 15, 15)), near)
    assert outline is not None
    assert outline[SHIRT].mean() > 0.97
    assert outline.mean() < 0.3


def test_empty_seed_falls_back_to_the_changed_pixel_outline_and_says_so(
    recolour: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # A thin changed strip: too narrow to hold any definite shirt.
    source = scene()
    far = source.copy()
    far[900:912, 300:1800] = 10
    run = write_run(tmp_path / "run", source, far, far)
    outline = recolour.automatic_outline(run, ["White", "Black"])
    assert outline.shape == (2048, 2048)
    assert outline[905, 1000]
    assert outline.mean() < 0.02
    assert "fell back" in capsys.readouterr().out


def test_review_refuses_a_pilot_that_changed_nothing(recolour: ModuleType, tmp_path: Path) -> None:
    source = scene()
    run = write_run(tmp_path / "run", source, source, source)
    with pytest.raises(SystemExit, match="changed nothing"):
        pilot(recolour, run, approve=False, reference=None)


def test_approve_saves_at_full_size_exactly_what_the_review_showed(
    recolour: ModuleType, run_dir: Path
) -> None:
    pilot(recolour, run_dir, approve=False, reference=None)
    with Image.open(run_dir / "review" / "pilot" / recolour.REVIEWED_MASK) as image:
        reviewed = np.asarray(image.convert("L")) > 0
    assert (run_dir / "review" / "pilot" / "outline.jpg").is_file()
    pilot(recolour, run_dir, approve=True, reference=None)
    assert saved_reference(recolour, run_dir).shape == (2048, 2048)
    assert np.array_equal(saved_reference(recolour, run_dir), reviewed)
    assert recorded_outline(run_dir) == "automatic"


def test_approve_needs_a_review(recolour: ModuleType, run_dir: Path) -> None:
    with pytest.raises(SystemExit, match="Run `pilot` first"):
        pilot(recolour, run_dir, approve=True, reference=None)


def test_approve_refuses_a_review_older_than_the_pilots(
    recolour: ModuleType, run_dir: Path
) -> None:
    pilot(recolour, run_dir, approve=False, reference=None)
    reviewed = run_dir / "review" / "pilot" / recolour.REVIEWED_MASK
    photo = run_dir / "out" / "black.png"
    later = reviewed.stat().st_mtime + 60
    os.utime(photo, (later, later))
    with pytest.raises(SystemExit, match="changed since"):
        pilot(recolour, run_dir, approve=True, reference=None)


def test_a_full_size_reference_loads_for_scoring_and_for_the_export(
    recolour: ModuleType, run_dir: Path
) -> None:
    mask = np.zeros((2048, 2048), np.uint8)
    mask[SHIRT] = 255
    Image.fromarray(mask).save(run_dir / recolour.REFERENCE_MASK)
    small = recolour.load_reference(run_dir)
    assert small.shape == (recolour.ANALYSIS_SIZE, recolour.ANALYSIS_SIZE)
    assert small[150:375, 125:387].all()
    assert small.mean() == pytest.approx((mask > 0).mean(), abs=0.002)
    assert np.array_equal(recolour.load_reference(run_dir, recolour.SIZE), mask > 0)


def test_an_existing_512px_reference_reads_as_it_always_did(
    recolour: ModuleType, run_dir: Path
) -> None:
    mask = np.zeros((512, 512), np.uint8)
    mask[150:375, 125:387] = 255
    Image.fromarray(mask).save(run_dir / recolour.REFERENCE_MASK)
    assert np.array_equal(recolour.load_reference(run_dir), mask > 0)
    full = recolour.load_reference(run_dir, recolour.SIZE)
    legacy = cv2.resize(mask // 255, (2048, 2048), interpolation=cv2.INTER_NEAREST)
    assert np.array_equal(recolour.shirt_alpha(full), recolour.shirt_alpha(legacy > 0))


def test_an_existing_512px_reference_drives_drift_and_assemble(
    recolour: ModuleType, run_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mask_png(run_dir / recolour.REFERENCE_MASK, 512, (125, 150, 387, 375))
    before = (run_dir / recolour.REFERENCE_MASK).read_bytes()
    meta_before = (run_dir / "run.json").read_text(encoding="utf-8")
    monkeypatch.setattr(recolour, "COLOURS", {"White": "#FFFFFF", "Black": "#000000"})
    overlays = run_dir / "overlays"
    overlays.mkdir()
    for colour in recolour.COLOURS:
        Image.new("RGBA", (8, 8)).save(overlays / f"{colour}.png")
    monkeypatch.setattr(recolour, "OVERLAY_DIR", overlays)

    recolour.drift(argparse.Namespace(run_dir=str(run_dir)))
    recolour.assemble(argparse.Namespace(run_dir=str(run_dir), upscale=False))

    report = json.loads((run_dir / "review" / "report.json").read_text(encoding="utf-8"))
    assert [row["drift_pct"] for row in report] == [0.0, 0.0]
    with Image.open(run_dir / "export" / "test - Black.png") as image:
        exported = np.asarray(image.convert("RGB"))
    assert exported[1000, 1000].max() < 40
    assert exported[100, 100, 1] > 90  # outside the shirt: the source's background
    assert (run_dir / recolour.REFERENCE_MASK).read_bytes() == before
    assert (run_dir / "run.json").read_text(encoding="utf-8") == meta_before


def test_approve_with_a_reference_installs_it_and_records_it(
    recolour: ModuleType, run_dir: Path, tmp_path: Path
) -> None:
    supplied = mask_png(tmp_path / "mask.png", 700, (170, 200, 530, 510))
    pilot(recolour, run_dir, approve=True, reference=supplied)
    installed = saved_reference(recolour, run_dir)
    assert installed.shape == (2048, 2048)
    assert installed[1000, 1000]
    assert not installed[100, 100]
    assert recorded_outline(run_dir) == "manual"
    assert PILOT_NOTE in (run_dir / "briefs" / "navy.md").read_text(encoding="utf-8")
    assert (run_dir / "review" / "pilot" / "outline-manual.jpg").is_file()


def test_a_reference_can_be_the_installed_mask_itself(recolour: ModuleType, run_dir: Path) -> None:
    path = mask_png(run_dir / recolour.REFERENCE_MASK, 512, (125, 150, 387, 375))
    pilot(recolour, run_dir, approve=True, reference=path)
    assert saved_reference(recolour, run_dir).shape == (2048, 2048)
    assert recorded_outline(run_dir) == "manual"


@pytest.mark.parametrize(
    ("mask", "message"),
    [
        (((300, 200), (10, 10, 50, 50)), "square"),
        (((256, 256), (0, 0, 0, 0)), "empty"),
        (((256, 256), (0, 0, 256, 256)), "whole frame"),
    ],
)
def test_a_supplied_mask_that_cannot_be_an_outline_is_refused(
    recolour: ModuleType,
    run_dir: Path,
    tmp_path: Path,
    mask: tuple[tuple[int, int], tuple[int, int, int, int]],
    message: str,
) -> None:
    path = tmp_path / "bad.png"
    size, box = mask
    image = Image.new("L", size)
    image.paste(255, box)
    image.save(path)
    with pytest.raises(SystemExit, match=message):
        pilot(recolour, run_dir, approve=True, reference=path)
    assert not (run_dir / recolour.REFERENCE_MASK).exists()
    assert recorded_outline(run_dir) is None


def test_a_missing_supplied_mask_is_refused(
    recolour: ModuleType, run_dir: Path, tmp_path: Path
) -> None:
    with pytest.raises(SystemExit, match="not found"):
        pilot(recolour, run_dir, approve=True, reference=tmp_path / "gone.png")


def test_reference_needs_approve(recolour: ModuleType, run_dir: Path, tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="--approve"):
        pilot(recolour, run_dir, approve=False, reference=tmp_path / "mask.png")


def test_approve_refuses_to_overwrite_a_manual_reference(
    recolour: ModuleType, run_dir: Path, tmp_path: Path
) -> None:
    pilot(recolour, run_dir, approve=False, reference=None)
    supplied = mask_png(tmp_path / "mask.png", 512, (125, 150, 387, 375))
    pilot(recolour, run_dir, approve=True, reference=supplied)
    before = (run_dir / recolour.REFERENCE_MASK).read_bytes()
    with pytest.raises(SystemExit, match="manual"):
        pilot(recolour, run_dir, approve=True, reference=None)
    assert (run_dir / recolour.REFERENCE_MASK).read_bytes() == before
    assert recorded_outline(run_dir) == "manual"


def test_a_reference_with_no_record_counts_as_automatic(
    recolour: ModuleType, run_dir: Path
) -> None:
    mask_png(run_dir / recolour.REFERENCE_MASK, 512, (125, 150, 387, 375))
    pilot(recolour, run_dir, approve=False, reference=None)
    pilot(recolour, run_dir, approve=True, reference=None)
    assert saved_reference(recolour, run_dir).shape == (2048, 2048)
    assert recorded_outline(run_dir) == "automatic"


def test_band_spill_counts_edge_pixels_wrong_in_both_photos(recolour: ModuleType) -> None:
    source, far = scene(), scene((15, 15, 15))
    outline = np.zeros((2048, 2048), bool)
    outline[SHIRT] = True
    assert recolour.band_spill(outline, source, far) < 1
    too_big = cv2.dilate(outline.astype(np.uint8), np.ones((49, 49), np.uint8)) > 0
    assert recolour.band_spill(too_big, source, far) > recolour.MAX_BAND_SPILL_PCT


def test_band_spill_needs_a_core_to_compare_with(recolour: ModuleType) -> None:
    outline = np.zeros((2048, 2048), bool)
    outline[1000:1020, 1000:1020] = True
    assert recolour.band_spill(outline, scene(), scene()) is None


def test_review_warns_about_band_spill_without_stopping(
    recolour: ModuleType, run_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    monkeypatch.setattr(recolour, "band_spill", lambda *_: 40.0)
    pilot(recolour, run_dir, approve=False, reference=None)
    assert "Band spill 40.0%" in capsys.readouterr().out


def test_largest_disagreement_names_the_lost_region_and_ignores_thin_edges(
    recolour: ModuleType,
) -> None:
    new = np.zeros((2048, 2048), bool)
    new[600:1500, 500:1500] = True
    old = np.zeros_like(new)
    old[598:1502, 498:1502] = True  # a thin difference all round
    assert recolour.largest_disagreement(old, new) is None
    old[1500:1700, 700:1000] = True  # the old outline's stray region
    region = recolour.largest_disagreement(old, new)
    assert region is not None
    left, top, right, bottom = region.box
    assert (left, right) == pytest.approx((700, 1000), abs=12)
    assert (top, bottom) == pytest.approx((1500, 1700), abs=12)
    assert region.side == "old"


def test_review_marks_the_disagreement_on_the_overlay(recolour: ModuleType, run_dir: Path) -> None:
    (run_dir / "review" / "pilot").mkdir(parents=True)
    outline = np.zeros((2048, 2048), bool)
    disagreement = recolour.Disagreement((100, 100, 300, 300), 40000, "old")
    plain = recolour.outline_overlay(run_dir, outline, "plain.jpg", None)
    marked = recolour.outline_overlay(run_dir, outline, "marked.jpg", disagreement)
    with Image.open(plain) as before, Image.open(marked) as after:
        assert not np.array_equal(np.asarray(before), np.asarray(after))

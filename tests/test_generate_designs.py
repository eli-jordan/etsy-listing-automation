"""The etsy-research-design skill's `generate_designs.py`: one print file per idea, cut
from the generator's flat background."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pytest
from PIL import Image

SCRIPT = Path(__file__).parents[1] / ".claude/skills/etsy-research-design/generate_designs.py"
GREEN = (0, 255, 0)
MAGENTA = (255, 0, 255)
RED = (200, 30, 30)
BLUE = (30, 30, 200)


@pytest.fixture(scope="module")
def designs() -> ModuleType:
    spec = importlib.util.spec_from_file_location("generate_designs", SCRIPT)
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_designs"] = module
    spec.loader.exec_module(module)
    return module


def flat_art(path: Path, background: tuple[int, int, int], ink: tuple[int, int, int]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (400, 500), background)
    image.paste(ink, (100, 100, 300, 400))
    image.save(path)


@pytest.fixture
def niche(tmp_path: Path) -> Path:
    for slug in ("01-a", "02-b", "03-c"):
        idea = tmp_path / "ideas" / slug
        idea.mkdir(parents=True)
        shirt = "printed on an ivory shirt (#f0ebdc), so it reads"
        (idea / "prompt.md").write_text(f"Draw it. It will be {shirt}.", encoding="utf-8")
        flat_art(idea / "refs" / "ref-1-123.jpg", (90, 90, 90), RED)
    return tmp_path


@pytest.fixture
def generated(designs: ModuleType, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Stands in for Kie.ai, recording each idea it was asked to generate."""
    done: list[str] = []

    def fake(url: str | None, _brief: Path, output: Path, _key: str, ratio: str) -> None:
        assert url == "uploaded-ref-1-123.jpg"
        assert ratio == "4:5"
        done.append(output.stem)
        flat_art(output, GREEN, RED)

    monkeypatch.setattr(designs.kie, "upload", lambda path, _key: f"uploaded-{path.name}")
    monkeypatch.setattr(designs.kie, "generate", fake)
    monkeypatch.setattr(designs.kie, "api_key", lambda: "key")
    monkeypatch.setattr(designs.kie, "balance", lambda _key: 1000.0)
    return done


@pytest.mark.parametrize("background", [GREEN, MAGENTA])
def test_the_print_file_is_transparent_and_full_size(
    designs: ModuleType, tmp_path: Path, background: tuple[int, int, int]
) -> None:
    raw, output = tmp_path / "raw.png", tmp_path / "out" / "design.png"
    flat_art(raw, background, RED)

    designs.cut_out(raw, output)

    with Image.open(output) as image:
        assert (image.size, image.mode) == ((4500, 5400), "RGBA")
        pixels = np.asarray(image)
    assert set(np.unique(pixels[..., 3]).tolist()) == {0, 255}
    assert tuple(pixels[0, 0]) == (0, 0, 0, 0)
    assert tuple(pixels[2500, 2250][:3]) == RED


def test_a_green_tint_is_taken_off_the_artwork(designs: ModuleType) -> None:
    tinted = np.array([[[180, 210, 60]]], dtype=np.uint8)
    assert designs.despill(tinted, GREEN).tolist() == [[[180, 180, 60]]]


def test_a_background_that_is_not_the_key_colour_is_refused(
    designs: ModuleType, tmp_path: Path
) -> None:
    raw = tmp_path / "raw.png"
    flat_art(raw, (240, 240, 240), RED)
    with pytest.raises(ValueError, match="neither green nor magenta"):
        designs.cut_out(raw, tmp_path / "out.png")


def test_with_no_slugs_only_ideas_without_a_print_file_are_generated(
    designs: ModuleType, niche: Path, generated: list[str]
) -> None:
    flat_art(niche / "ideas/01-a/out/01-a.png", GREEN, RED)

    designs.generate(niche, [])

    assert sorted(generated) == ["02-b", "03-c"]
    assert (niche / "ideas/02-b/out/02-b.png").exists()


def test_a_saved_generator_image_is_cut_without_paying_again(
    designs: ModuleType, niche: Path, generated: list[str]
) -> None:
    flat_art(niche / "ideas/01-a/raw/01-a.png", GREEN, RED)

    designs.generate(niche, [])

    assert sorted(generated) == ["02-b", "03-c"]
    assert (niche / "ideas/01-a/out/01-a.png").exists()


def test_naming_a_slug_regenerates_it(
    designs: ModuleType, niche: Path, generated: list[str]
) -> None:
    designs.generate(niche, [])
    generated.clear()

    designs.generate(niche, ["02-b"])

    assert generated == ["02-b"]


def test_an_unknown_slug_stops_before_anything_is_generated(
    designs: ModuleType, niche: Path, generated: list[str]
) -> None:
    with pytest.raises(SystemExit, match="99-z"):
        designs.generate(niche, ["02-b", "99-z"])
    assert generated == []


@pytest.mark.parametrize("extra_references", [0, 2])
def test_an_idea_without_exactly_one_reference_stops_before_spending(
    designs: ModuleType, niche: Path, generated: list[str], extra_references: int
) -> None:
    refs = niche / "ideas/02-b/refs"
    if extra_references:
        flat_art(refs / "ref-2-456.jpg", (90, 90, 90), RED)
    else:
        (refs / "ref-1-123.jpg").unlink()

    with pytest.raises(SystemExit, match=r"exactly one.*02-b"):
        designs.generate(niche, [])

    assert generated == []


def test_the_sheet_tiles_each_design_on_its_shirt_colour(
    designs: ModuleType, niche: Path, generated: list[str]
) -> None:
    designs.generate(niche, [])

    designs.sheet(niche)

    with Image.open(niche / "designs-overview.jpg") as image:
        tiled = image.convert("RGB")
    corner = tiled.getpixel((5, 30))
    beside = tiled.getpixel((425, 30))
    assert all(abs(a - b) < 6 for a, b in zip(corner, (240, 235, 220), strict=True))
    assert all(abs(channel - 90) < 6 for channel in beside)
    assert len(generated) == 3


def test_archive_numbers_versions_and_skips_an_unchanged_print(
    designs: ModuleType, niche: Path, generated: list[str]
) -> None:
    designs.generate(niche, [])
    idea = niche / "ideas/01-a"

    first = designs.archive(idea)
    again = designs.archive(idea)
    flat_art(idea / "out/01-a.png", MAGENTA, RED)
    second = designs.archive(idea)

    assert first == again == idea / "rejected/01-a-v1.png"
    assert second == idea / "rejected/01-a-v2.png"


def test_revise_edits_the_current_print_on_its_key_colour(
    designs: ModuleType, niche: Path, generated: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    designs.generate(niche, [])
    idea = niche / "ideas/01-a"
    sent: dict[str, Any] = {}

    def fake_edit(url: str, brief: Path, output: Path, _key: str, _ratio: str) -> None:
        sent.update(url=url, prompt=brief.read_text(encoding="utf-8"))
        flat_art(output, GREEN, BLUE)

    monkeypatch.setattr(designs.kie, "generate", fake_edit)
    change = niche / "change.txt"
    change.write_text("Make the block blue.", encoding="utf-8")

    designs.revise(idea, change)

    assert sent["url"] == "uploaded-01-a-edit-source.png"
    assert "Make the block blue." in sent["prompt"]
    assert "#00FF00" in sent["prompt"]
    with Image.open(idea / "raw/01-a-edit-source.png") as source:
        assert source.getpixel((5, 5)) == GREEN
    with Image.open(idea / "out/01-a.png") as image:
        assert image.getpixel((2250, 2500))[:3] == BLUE
    assert (idea / "rejected/01-a-v1.png").exists()


def test_the_prompts_key_colour_wins_over_green(designs: ModuleType, tmp_path: Path) -> None:
    (tmp_path / "prompt.md").write_text(
        "a flat solid magenta background (#FF00FF) that fills it", encoding="utf-8"
    )
    assert designs.idea_key(tmp_path) == MAGENTA


def test_an_upscale_keeps_the_original_edges_and_transparency(
    designs: ModuleType, niche: Path, generated: list[str]
) -> None:
    designs.generate(niche, [])
    idea = niche / "ideas/01-a"
    with Image.open(idea / "out/01-a.png") as image:
        before = np.asarray(image)

    source = designs.upscale_source(idea)
    with Image.open(source) as image:
        assert max(image.size) == 1600
        upscaled = image.resize((image.width * 2, image.height * 2))
    upscaled.paste((20, 20, 200), (0, 0, upscaled.width, upscaled.height))
    upscaled.save(niche / "kittl.jpg")
    designs.upscale_apply(idea, niche / "kittl.jpg")

    with Image.open(idea / "out/01-a.png") as image:
        after = np.asarray(image)
    assert (after[..., 3] == before[..., 3]).all()
    ys, xs = np.nonzero(before[..., 3])
    assert tuple(after[ys[0], xs[0], :3]) == tuple(before[ys[0], xs[0], :3])
    middle = (ys.min() + ys.max()) // 2, (xs.min() + xs.max()) // 2
    assert all(abs(a - b) < 6 for a, b in zip(after[middle][:3], (20, 20, 200), strict=True))
    assert (idea / "out-pre-upscale/01-a.png").exists()


def test_an_upscale_of_the_wrong_shape_is_refused(
    designs: ModuleType, niche: Path, generated: list[str]
) -> None:
    designs.generate(niche, [])
    Image.new("RGB", (900, 300)).save(niche / "wide.jpg")
    with pytest.raises(SystemExit, match="not the shape"):
        designs.upscale_apply(niche / "ideas/01-a", niche / "wide.jpg")


def test_check_names_what_is_not_print_ready(
    designs: ModuleType, niche: Path, generated: list[str], capsys: pytest.CaptureFixture[str]
) -> None:
    designs.generate(niche, [])
    Image.new("RGBA", (450, 540), RED).save(niche / "ideas/02-b/out/02-b.png")
    Image.new("RGB", (928, 1152), GREEN).save(niche / "ideas/03-c/raw/03-c.png")
    capsys.readouterr()

    designs.check(niche)

    lines = dict(line.split(": ", 1) for line in capsys.readouterr().out.splitlines())
    assert lines["01-a"].startswith("ok")
    assert "crowded" in lines["01-a"]  # one solid block fills its whole box
    assert lines["02-b"].startswith("450x540 RGBA")
    assert "1K" in lines["03-c"]


def test_an_older_print_file_name_is_still_found(designs: ModuleType, tmp_path: Path) -> None:
    flat_art(tmp_path / "02-b" / "out" / "b.png", GREEN, RED)
    assert designs.print_path(tmp_path / "02-b").name == "b.png"

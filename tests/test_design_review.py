"""The design-review skill's `review.py`: scan idea folders into review.json, build the
review page, and read the seller's tags back."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from PIL import Image

SCRIPT = Path(__file__).parents[1] / ".claude/skills/design-review/review.py"

KIE_PROMPT = (
    'The artwork includes exactly this text, spelled exactly, on these lines: "Starry New Year", '
    "set in a bold script.\n"
    "Concept: Van Gogh's Starry Night with firework stars.\n"
    "It will be printed on a black shirt (#1c1c1c), so every element must read clearly.\n"
)
CODEX_PROMPT = (
    "- **Concept:** A Sankofa bird cut as a folk linocut.\n"
    '- **Text:** exactly "Sankofa / Go Back And Fetch It", letter case as shown; "/" marks a '
    "line break.\n"
    "- **Printed on:** a moss t-shirt, so the artwork must read clearly on that colour.\n"
)


@pytest.fixture(scope="module")
def review() -> ModuleType:
    spec = importlib.util.spec_from_file_location("design_review", SCRIPT)
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["design_review"] = module
    spec.loader.exec_module(module)
    return module


def make_idea(ideas: Path, name: str, prompt: str, refs: list[str]) -> Path:
    idea = ideas / name
    (idea / "out").mkdir(parents=True)
    art = Image.new("RGBA", (450, 540), (0, 0, 0, 0))
    art.paste((255, 0, 0, 255), (100, 100, 350, 440))
    art.save(idea / "out" / f"{name}.png")
    (idea / "prompt.md").write_text(prompt, encoding="utf8")
    if refs:
        (idea / "refs").mkdir()
    for ref in refs:
        Image.new("RGB", (300, 200), (0, 0, 255)).save(idea / "refs" / ref)
    return idea


@pytest.fixture
def run(tmp_path: Path) -> Path:
    ideas = tmp_path / "nye-2026-11-20" / "ideas"
    make_idea(ideas, "01-starry-new-year", KIE_PROMPT, ["ref-1-4496909341.jpg"])
    make_idea(ideas, "02-sankofa", CODEX_PROMPT, [])
    (ideas / "03-no-print-yet").mkdir()
    rejected = ideas / "rejected" / "out"
    rejected.mkdir(parents=True)
    Image.new("RGBA", (10, 10)).save(rejected / "old.png")
    return ideas


def fill(review_dir: Path) -> dict:
    data = json.loads((review_dir / "review.json").read_text(encoding="utf8"))
    data["title"], data["intro"] = "Test Review", "Two designs."
    data["groups"][0]["name"] = "Round 1"
    for d in data["designs"]:
        d["style"], d["idea"] = "Neon line art", "A test idea."
    (review_dir / "review.json").write_text(json.dumps(data), encoding="utf8")
    return data


def test_scan_reads_both_prompt_formats(review: ModuleType, run: Path, tmp_path: Path) -> None:
    out = tmp_path / "review"
    review.scan(out, [run])
    designs = json.loads((out / "review.json").read_text(encoding="utf8"))["designs"]
    by_n = {d["n"]: d for d in designs}
    assert sorted(by_n) == ["01", "02"]
    assert by_n["01"]["title"] == "Starry New Year"
    assert (by_n["01"]["shirtName"], by_n["01"]["shirt"]) == ("Black", "#1c1c1c")
    assert by_n["01"]["concept"].startswith("Van Gogh")
    assert by_n["01"]["refs"][0]["link"] == "https://www.etsy.com/listing/4496909341"
    assert by_n["02"]["title"] == "Sankofa / Go Back And Fetch It"
    assert (by_n["02"]["shirtName"], by_n["02"]["shirt"]) == ("Moss", "#707a5c")
    assert by_n["02"]["refs"] == []


def test_scan_again_keeps_filled_records(review: ModuleType, run: Path, tmp_path: Path) -> None:
    out = tmp_path / "review"
    review.scan(out, [run])
    fill(out)
    review.scan(out, [run])
    designs = json.loads((out / "review.json").read_text(encoding="utf8"))["designs"]
    assert len(designs) == 2
    assert all(d["idea"] == "A test idea." for d in designs)


def test_build_refuses_gaps(review: ModuleType, run: Path, tmp_path: Path) -> None:
    out = tmp_path / "review"
    review.scan(out, [run])
    with pytest.raises(SystemExit):
        review.build(out)
    assert not (out / "site" / "design-review.html").exists()


def test_build_writes_page_images_and_batches(
    review: ModuleType, run: Path, tmp_path: Path
) -> None:
    out = tmp_path / "review"
    review.scan(out, [run])
    fill(out)
    review.build(out)
    html = (out / "site" / "design-review.html").read_text(encoding="utf8")
    assert "<title>Test Review</title>" in html
    assert "__DATA__" not in html
    webps = sorted(p.name for p in (out / "site" / "d").iterdir())
    assert len(webps) == 4
    with Image.open(next((out / "site" / "d").glob("*01-starry*-s.webp"))) as im:
        assert im.mode == "RGBA"
    plan = json.loads((out / "publish-batches.json").read_text(encoding="utf8"))
    assert sum(len(b) for b in plan) == 6
    assert "design-review.html" not in plan[0]


def test_batches_split_at_the_file_limit(
    review: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(review, "BATCH_FILES", 2)
    site = tmp_path / "site"
    site.mkdir()
    for i in range(5):
        (site / f"{i}.jpg").write_bytes(b"x")
    html = site / "design-review.html"
    html.write_text("", encoding="utf8")
    assert [len(b) for b in review.batches(site, html)] == [2, 2, 1]


def test_results_groups_tags(review: ModuleType, run: Path, tmp_path: Path) -> None:
    out = tmp_path / "review"
    review.scan(out, [run])
    data = fill(out)
    ids = [d["id"] for d in data["designs"]]
    rows = tmp_path / "tags.txt"
    rows.write_text(
        '2 documents from collection "reviews":\n'
        + json.dumps({"id": ids[0], "data": {"verdict": "iterate", "note": "bigger text"}})
        + "\n",
        encoding="utf8",
    )
    review.results(out, rows)
    recs = {r["id"]: r for r in json.loads((out / "review-results.json").read_text("utf8"))}
    assert recs[ids[0]]["verdict"] == "iterate"
    assert recs[ids[0]]["note"] == "bigger text"
    assert recs[ids[1]]["verdict"] == "untagged"

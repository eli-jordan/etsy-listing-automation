"""Generator prompts, the ideas report and the seller's picks for Etsy design research.

    uv run python design_ideas.py briefs NICHE_RUN --general GENERAL_RUN [--downloads RUN]
    uv run python design_ideas.py report NICHE_RUN --general GENERAL_RUN [--downloads RUN]
    uv run python design_ideas.py picked NICHE_RUN DECISIONS_FOLDER

All three read NICHE_RUN/ideas.json (written by the agent; SKILL.md step 7 gives
its shape), whose `ideas` list runs from the idea expected to sell best to the
one expected to sell worst.

`briefs` gives each idea a folder NICHE_RUN/ideas/<slug>/ holding prompt.md
(design-prompt.md filled in: the whole prompt generate_designs.py sends to the
generator), refs/ with its one style reference downloaded at full size, and an
empty out/. It also tiles every reference into NICHE_RUN/ideas/refs-overview.jpg
for a visual check.

`report` writes NICHE_RUN/report.html from ideas.json, tally.json, the two
runs' listings and each idea's reference image: one card per idea, in rank
order, with a Generate / Skip choice saved to the page's `decisions` store.

`picked` reads the decisions saved from that store (ArtifactData `list` with
out_dir), lists every idea marked Generate in rank order, and prints the
generate_designs.py command that makes them.
"""

from __future__ import annotations

import argparse
import base64
import html
import io
import json
import re
import sys
from pathlib import Path
from typing import Any

import httpx
from design_sheets import _font, _read_json, listing_score
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parents[1] / "design-review"))
from review import SHIRTS  # the review page shows each shirt in the same colour

HERE = Path(__file__).parent
GREEN_KEY = ("pure green", "#00FF00")
MAGENTA_KEY = ("magenta", "#FF00FF")
GREENISH = re.compile(r"green|teal|lime|olive|mint|emerald|jade|sage|moss", re.IGNORECASE)
REQUIRED = (
    "slug", "name", "concept", "hook", "direction", "palette", "garment", "ref",
    "general_tags", "niche_tags", "phrase", "template", "forecast", "why",
)  # fmt: skip
FORECASTS = ("strong", "good", "long shot")
THUMB = 560  # report reference image, longest side in px
TILE = 300  # refs-overview cell
FRESH_PHRASE = 20  # phrase count at or under this: nobody sells it yet
TAKEN_PHRASE = 100
OPEN_TEMPLATE = 500
CROWDED_TEMPLATE = 3000

Json = dict[str, Any]


def _idea_problems(idea: Json) -> list[str]:
    problems = []
    missing = [key for key in REQUIRED if key not in idea]
    if missing:
        problems.append(f"missing {', '.join(missing)}")
    if idea.get("forecast") not in FORECASTS:
        problems.append(f"forecast must be one of {', '.join(FORECASTS)}")
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", idea.get("slug", "")):
        problems.append("slug must be lower-case words joined by hyphens")
    return problems


def load_ideas(niche: Path) -> Json:
    doc: Json = _read_json(niche / "ideas.json")
    ideas = doc.get("ideas", [])
    problems = [
        f"idea {number}: {problem}"
        for number, idea in enumerate(ideas, 1)
        for problem in _idea_problems(idea)
    ]
    slugs = [idea.get("slug") for idea in ideas]
    problems += [
        f"slug {s} is used twice" for s in sorted({s for s in slugs if s}) if slugs.count(s) > 1
    ]
    if problems:
        sys.exit("fix ideas.json:\n  " + "\n  ".join(problems))
    return doc


# ---------------------------------------------------------------- briefs


def _image_record(runs: list[Path], listing: int, rank: int) -> Json:
    for run in runs:
        for image in _read_json(run / "images.json"):
            if image["listing_id"] == listing and image["rank"] == rank:
                return dict(image)
    sys.exit(f"no image {listing}:{rank} in {', '.join(r.name for r in runs)}")


def ref_path(niche: Path, idea: Json) -> Path:
    slug, listing = str(idea["slug"]), idea["ref"]["listing"]
    return niche / "ideas" / slug / "refs" / f"ref-{listing}.jpg"


def _fetch_ref(client: httpx.Client, runs: list[Path], niche: Path, idea: Json) -> Path:
    dest = ref_path(niche, idea)
    dest.parent.mkdir(parents=True, exist_ok=True)
    for other in dest.parent.iterdir():
        if other != dest:
            other.unlink()  # exactly one reference per brief
    if not dest.exists():
        record = _image_record(runs, int(idea["ref"]["listing"]), int(idea["ref"].get("image", 1)))
        response = client.get(record["url_full"])
        response.raise_for_status()
        dest.write_bytes(response.content)
    return dest


def text_line(idea: Json) -> str:
    text = idea.get("text")
    if not text:
        return "The artwork has no text, letters, numbers, signatures or watermarks."
    lines = " | ".join(f'"{line.strip()}"' for line in text.split(" / "))
    line = (
        "The artwork includes exactly this text, spelled exactly, letter case as shown, "
        f"on these lines: {lines}."
    )
    labels = idea.get("labels") or []
    if labels:
        quoted = ", ".join(f'"{label}"' for label in labels)
        line += f" Plus {len(labels)} small labels, exactly: {quoted}."
    if idea.get("text_note"):
        line += f" {idea['text_note'].rstrip('.')}."
    return (
        f"{line} The words are part of the artwork, following a shape, woven into a pattern "
        "or carried by its motion, rather than a caption set above or below it, and they sit "
        "in the upper half of the design. No other words, letters, numbers, signatures or "
        "watermarks anywhere."
    )


def garment_hex(idea: Json) -> str:
    found = idea.get("garment_hex") or SHIRTS.get(str(idea["garment"]).lower())
    if not found:
        known = ", ".join(sorted(SHIRTS))
        sys.exit(
            f"{idea['slug']}: no colour for garment {idea['garment']!r}; "
            f"add garment_hex or use one of {known}"
        )
    return str(found)


def fill_brief(idea: Json) -> str:
    page = (HERE / "design-prompt.md").read_text(encoding="utf-8")
    key_name, key_hex = MAGENTA_KEY if GREENISH.search(idea["palette"]) else GREEN_KEY
    fields = {
        "KEY_NAME": key_name,
        "KEY_HEX": key_hex,
        "CONCEPT": idea["concept"],
        "TEXT": text_line(idea),
        "DIRECTION": idea["direction"].replace("{slug}", idea["slug"]),
        "TAKE": idea["ref"]["take"].rstrip("."),
        "PALETTE": idea["palette"],
        "GARMENT": idea["garment"],
        "GARMENT_HEX": garment_hex(idea),
    }
    for key, value in fields.items():
        page = page.replace(f"__{key}__", value)
    if re.search(r"__[A-Z_]+__", page):
        sys.exit(f"{idea['slug']}: design-prompt.md has a placeholder briefs doesn't fill")
    return page


def _overview(niche: Path, ideas: list[Json]) -> Path:
    columns = 5
    rows = -(-len(ideas) // columns)
    sheet = Image.new("RGB", (columns * TILE, rows * (TILE + 28)), "white")
    draw = ImageDraw.Draw(sheet)
    for number, idea in enumerate(ideas):
        x, y = (number % columns) * TILE, (number // columns) * (TILE + 28)
        tile = Image.open(ref_path(niche, idea)).convert("RGB")
        tile.thumbnail((TILE - 8, TILE - 8))
        sheet.paste(tile, (x + 4, y + 28))
        draw.text(
            (x + 4, y + 4), f"{number + 1}. {idea['slug']}"[:40], fill="black", font=_font(15)
        )
    out = niche / "ideas" / "refs-overview.jpg"
    sheet.save(out, quality=85)
    return out


def briefs(niche: Path, general: Path, downloads: Path | None = None) -> None:
    ideas = load_ideas(niche)["ideas"]
    runs = [general, niche, *([downloads] if downloads else [])]
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        for idea in ideas:
            _fetch_ref(client, runs, niche, idea)
            folder = niche / "ideas" / idea["slug"]
            (folder / "out").mkdir(exist_ok=True)
            (folder / "prompt.md").write_bytes(fill_brief(idea).encode("utf-8"))
    known = {idea["slug"] for idea in ideas}
    stale = [p.name for p in (niche / "ideas").iterdir() if p.is_dir() and p.name not in known]
    if stale:
        sys.stdout.write(f"folders not in ideas.json (left alone): {', '.join(sorted(stale))}\n")
    sys.stdout.write(f"{len(ideas)} briefs in {niche / 'ideas'}\n{_overview(niche, ideas)}\n")


# ---------------------------------------------------------------- report


def _tag_lookup(tally: Json) -> dict[str, list[tuple[str, Json]]]:
    found: dict[str, list[tuple[str, Json]]] = {}
    for field, rows in tally.items():
        for row in rows:
            found.setdefault(row["tag"], []).append((field, row))
            found.setdefault(f"{field}:{row['tag']}", []).append((field, row))
    return found


def _tag(name: str, side: str, lookup: dict[str, list[tuple[str, Json]]], runs: list[str]) -> Json:
    hits = lookup.get(name.lower())
    if not hits:
        sys.exit(f"tag {name!r} is not in tally.json; spell it as tally prints it")
    field, row = max(hits, key=lambda hit: hit[1]["total"])  # bare tag: its strongest field

    def cell(run: str) -> Json | None:
        value = row.get(run)
        return {"w": round(value["weight"], 1), "s": value["shops"]} if value else None

    return {"tag": row["tag"], "field": field, "side": side, "gap": row["gap"],
            "g": cell(runs[0]), "n": cell(runs[1])}  # fmt: skip


def _listing_rows(general: Path, niche: Path, downloads: Path | None) -> dict[int, Json]:
    rows: dict[int, Json] = {}
    sides = [
        (general, "general"),
        (niche, "niche"),
        *([(downloads, "downloads")] if downloads else []),
    ]
    for run, side in sides:
        for item in _read_json(run / "listings.json"):
            rows.setdefault(
                item["listing_id"],
                {
                    "id": item["listing_id"],
                    "run": side,
                    "shop": item.get("shop_name") or "",
                    "title": html.unescape(item.get("title") or ""),
                    "favs": item.get("num_favorers", 0),
                    "score": round(listing_score(item), 1),
                    "badges": item.get("badges", []),
                    "url": item.get("url") or "",
                },
            )
    return rows


def _thumb(path: Path) -> str:
    image = Image.open(path).convert("RGB")
    image.thumbnail((THUMB, THUMB))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _listing(listings: dict[int, Json], listing_id: int, slug: str) -> Json:
    if int(listing_id) not in listings:
        sys.exit(f"{slug}: listing {listing_id} is in neither run")
    return listings[int(listing_id)]


def _card(niche: Path, idea: Json, ctx: Json) -> Json:
    path = ref_path(niche, idea)
    if not path.exists():
        sys.exit(f"{path} is missing; run briefs first")
    tags = [_tag(t, "general", ctx["lookup"], ctx["runs"]) for t in idea["general_tags"]]
    tags += [_tag(t, "niche", ctx["lookup"], ctx["runs"]) for t in idea["niche_tags"]]
    ref = dict(_listing(ctx["listings"], idea["ref"]["listing"], idea["slug"]))
    ref.update(take=idea["ref"]["take"], img=_thumb(path))
    examples = [_listing(ctx["listings"], i, idea["slug"]) for i in idea.get("examples", [])]
    keep = ("slug", "name", "text", "labels", "concept", "hook", "direction", "palette",
            "garment", "phrase", "template", "forecast", "why")  # fmt: skip
    card = {key: idea.get(key) for key in keep}
    card.update(tags=tags, ref=ref, examples=examples, brief=str(path.parents[1] / "prompt.md"))
    return card


def report(niche: Path, general: Path, downloads: Path | None = None) -> None:
    doc = load_ideas(niche)
    ctx = {
        "lookup": _tag_lookup(_read_json(niche / "tally.json")),
        "runs": [general.name, niche.name],
        "listings": _listing_rows(general, niche, downloads),
    }
    cards = [_card(niche, idea, ctx) for idea in doc["ideas"]]
    limits = {"freshPhrase": FRESH_PHRASE, "takenPhrase": TAKEN_PHRASE,
              "openTemplate": OPEN_TEMPLATE, "crowdedTemplate": CROWDED_TEMPLATE}  # fmt: skip
    data = {"ideas": cards, "runs": {"general": general.name, "niche": niche.name}, **limits}
    page = (HERE / "report_template.html").read_text(encoding="utf-8")
    for key in ("title", "heading", "meta", "lede"):
        page = page.replace(f"__{key.upper()}__", doc[key])
    for key in ("findings", "notes"):
        page = page.replace(f"__{key.upper()}__", "".join(f"<li>{x}</li>" for x in doc[key]))
    raw = json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")
    page = page.replace("__KEY__", "nis-ideas-" + niche.name).replace("__DATA__", raw)
    out = niche / "report.html"
    out.write_bytes(page.encode("utf-8"))
    size = out.stat().st_size / 1e6
    sys.stdout.write(f"{out}: {len(cards)} ideas, {size:.1f} MB\n")


# ---------------------------------------------------------------- picked


def read_decisions(folder: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in folder.rglob("*.json"):
        body = json.loads(path.read_text(encoding="utf-8"))
        decision = body.get("decision") or (body.get("data") or {}).get("decision")
        if decision:
            out[path.stem] = decision
    return out


def picked(niche: Path, folder: Path) -> None:
    ideas = load_ideas(niche)["ideas"]
    decisions = read_decisions(folder)
    chosen = [i for i in ideas if decisions.get(i["slug"]) == "generate"]
    skipped = sum(1 for i in ideas if decisions.get(i["slug"]) == "skip")
    for number, idea in enumerate(ideas, 1):
        if idea in chosen:
            sys.stdout.write(f"{number}. {idea['name']}: {niche / 'ideas' / idea['slug']}\n")
    undecided = len(ideas) - len(chosen) - skipped
    sys.stdout.write(f"{len(chosen)} to generate, {skipped} skipped, {undecided} undecided\n")
    if chosen:
        slugs = " ".join(idea["slug"] for idea in chosen)
        sys.stdout.write(
            "uv run python .claude/skills/etsy-research-design/generate_designs.py "
            f"generate {niche} {slugs}\n"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("briefs", "report"):
        cmd = sub.add_parser(name)
        cmd.add_argument("niche", type=Path)
        cmd.add_argument("--general", type=Path, required=True)
        cmd.add_argument("--downloads", type=Path, help="the digital-download run, if any")
    pick = sub.add_parser("picked")
    pick.add_argument("niche", type=Path)
    pick.add_argument("decisions", type=Path, help="the out_dir ArtifactData saved them to")
    args = parser.parse_args()
    if args.command == "briefs":
        briefs(args.niche, args.general, args.downloads)
    elif args.command == "report":
        report(args.niche, args.general, args.downloads)
    else:
        picked(args.niche, args.decisions)


if __name__ == "__main__":
    main()

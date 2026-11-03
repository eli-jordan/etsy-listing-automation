"""Contact sheets and pattern tallies for Etsy design research.

    uv run python design_sheets.py sheets RUN_DIR [--top 60] [--per-sheet 6] [--match a,b]
        [--exclude a,b]
    uv run python design_sheets.py tally GENERAL_RUN NICHE_RUN
    uv run python design_sheets.py refs OUT_DIR LISTING_ID[:RANK] ... --runs RUN_DIR ...

`sheets` ranks the listings that fetch_listings.py wrote to RUN_DIR by
performance score (after --match keeps only listings whose title contains
one of its words and --exclude drops those whose title contains one of its)
and tiles the top ones, first two images each, into
RUN_DIR/sheets/NN.jpg. Every cell is captioned with its rank, listing ID,
score, favourites, badges, shop and title. RUN_DIR/sheets/index.json lists the
listings in rank order.

`tally` reads RUN_DIR/designs.jsonl (one design record per listing, written by
the agent from the sheets; records with "off_topic": true are skipped)
and prints, for each tag field, every tag's
performance-weighted support in each run. Each shop counts its best listing
in full and its other listings a quarter. The first run is the general
category; tags strong there but absent from the others are flagged `gap`.
Writes tally.json into the last (niche) run.

`refs` downloads full-size listing images (rank 1 unless given) from the
runs' images.json into OUT_DIR as ref-N-<listing>.jpg, for style references.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import sys
import textwrap
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx
from PIL import Image, ImageDraw, ImageFont

# Same listing score as etsy-research-proven-mockups/cluster_mockups.py.
VIEWS_WEIGHT = 0.5
BESTSELLER_BONUS = 1.0
POPULAR_BONUS = 0.5
SAME_SHOP_WEIGHT = 0.25

FIELDS = ("theme", "tone", "style", "layout", "typography", "elements", "colours", "pattern")
BOX = 400  # each image fits in a BOX x BOX square
CAPTION = 64
PAD = 12
COLUMNS = 2  # listings per sheet row
SHOTS = 2  # images per listing on a sheet
GAP_SHARE = 0.4  # general tags at least this share of the top general tag can be gaps
GAP_MIN_SHOPS = 2
TABLE_ROWS = 15
MIN_RUNS_FOR_GAP = 2  # a gap compares the general run against at least one other

Support = dict[str, dict[str, dict[str, float]]]


def listing_score(listing: dict[str, Any]) -> float:
    badges = set(listing.get("badges", []))
    best = "Bestseller" in badges or any(
        "is_best_seller" in hit.get("filters", []) for hit in listing.get("hits", [])
    )
    return (
        math.log10(1 + listing.get("num_favorers", 0))
        + VIEWS_WEIGHT * math.log10(1 + listing.get("views", 0))
        + (BESTSELLER_BONUS if best else 0)
        + (POPULAR_BONUS if "Popular now" in badges else 0)
    )


def _read_json(path: Path) -> Any:
    if not path.exists():
        sys.exit(f"{path} is missing; run fetch_listings.py on {path.parent} first")
    return json.loads(path.read_text(encoding="utf-8"))


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for name in ("arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _matches(listing: dict[str, Any], words: list[str], exclude: list[str]) -> bool:
    # Titles only: sellers pad tags with niche keywords ("teacher gift") on unrelated designs.
    text = html.unescape(listing.get("title") or "").lower()
    wanted = not words or any(word in text for word in words)
    return wanted and not any(word in text for word in exclude)


def _ranked(
    run: Path, top: int, words: list[str], exclude: list[str]
) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]]]:
    by_listing: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for image in _read_json(run / "images.json"):
        by_listing[image["listing_id"]].append(image)
    listings = _read_json(run / "listings.json")
    kept = [
        item
        for item in listings
        if by_listing[item["listing_id"]] and _matches(item, words, exclude)
    ]
    if words or exclude:
        sys.stdout.write(f"{len(kept)} of {len(listings)} listings pass the title filters\n")
    return sorted(kept, key=listing_score, reverse=True)[:top], by_listing


def _index_row(rank: int, sheet: str, listing: dict[str, Any]) -> dict[str, Any]:
    return {
        "rank": rank,
        "sheet": sheet,
        "listing_id": listing["listing_id"],
        "shop_id": listing["shop_id"],
        "shop_name": listing.get("shop_name"),
        "title": html.unescape(listing.get("title") or ""),
        "score": round(listing_score(listing), 2),
        "num_favorers": listing.get("num_favorers", 0),
        "badges": listing.get("badges", []),
        "url": listing.get("url"),
    }


def _draw_cell(
    sheet: Image.Image, origin: tuple[int, int], row: dict[str, Any], shots: list[Path]
) -> None:
    x, y = origin
    draw = ImageDraw.Draw(sheet)
    badges = "".join(b[0] for b in row["badges"])
    head = (
        f"#{row['rank']}  {row['listing_id']}  score {row['score']:.1f}  "
        f"fav {row['num_favorers']}  {badges}  {row['shop_name'] or ''}"
    )
    draw.text((x, y), head, fill="black", font=_font(18))
    title = textwrap.shorten(row["title"] or "", width=110, placeholder="...")
    draw.text((x, y + 26), title, fill="#444", font=_font(15))
    for k, path in enumerate(shots):
        tile = Image.open(path).convert("RGB")
        tile.thumbnail((BOX, BOX))
        sheet.paste(tile, (x + k * (BOX + PAD), y + CAPTION))


def sheets(run: Path, top: int, per_sheet: int, words: list[str], exclude: list[str]) -> None:
    ranked, by_listing = _ranked(run, top, words, exclude)
    out = run / "sheets"
    out.mkdir(exist_ok=True)
    for old in out.glob("*.jpg"):
        old.unlink()

    cell_w, cell_h = SHOTS * BOX + PAD, CAPTION + BOX
    size = (
        COLUMNS * cell_w + (COLUMNS + 1) * PAD,
        math.ceil(per_sheet / COLUMNS) * (cell_h + PAD) + PAD,
    )
    index = []
    for start in range(0, len(ranked), per_sheet):
        name = f"{start // per_sheet + 1:02d}.jpg"
        sheet = Image.new("RGB", size, "white")
        for offset, listing in enumerate(ranked[start : start + per_sheet]):
            row = _index_row(start + offset + 1, name, listing)
            images = sorted(by_listing[listing["listing_id"]], key=lambda i: i["rank"])
            origin = (
                PAD + (offset % COLUMNS) * (cell_w + PAD),
                PAD + (offset // COLUMNS) * (cell_h + PAD),
            )
            _draw_cell(sheet, origin, row, [run / i["file"] for i in images[:SHOTS]])
            index.append(row)
        sheet.save(out / name, quality=88)

    (out / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    pages = math.ceil(len(index) / per_sheet)
    sys.stdout.write(f"{len(index)} listings on {pages} sheets in {out}\n")


def _designs(run: Path) -> list[dict[str, Any]]:
    path = run / "designs.jsonl"
    if not path.exists():
        sys.exit(f"{path} is missing; annotate the sheets first")
    records = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as error:
            sys.exit(f"{path}:{number}: {error}")
    return records


def _tags(record: dict[str, Any], field: str) -> set[str]:
    value = record.get(field) or []
    values = value if isinstance(value, list) else [value]
    return {str(v).strip().lower() for v in values if str(v).strip()}


def _check(run: Path, records: list[dict[str, Any]], listings: dict[int, Any]) -> None:
    for record in records:
        if record.get("listing_id") not in listings:
            sys.stderr.write(f"warning: {run.name}: {record.get('listing_id')} not in listings\n")
    index_path = run / "sheets" / "index.json"
    if not index_path.exists():
        return
    annotated = {r.get("listing_id") for r in records}
    missing = [i for i in _read_json(index_path) if i["listing_id"] not in annotated]
    if missing:
        sys.stderr.write(f"warning: {run.name}: {len(missing)} sheet listings not annotated\n")


def _weigh(shops: dict[int, list[float]]) -> dict[str, float]:
    weight = 0.0
    for scores in shops.values():
        ordered = sorted(scores, reverse=True)
        weight += ordered[0] + SAME_SHOP_WEIGHT * sum(ordered[1:])
    listings = sum(len(s) for s in shops.values())
    return {"weight": round(weight, 2), "shops": len(shops), "listings": listings}


def _on_sheets(run: Path, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep only records for listings the current sheets show, so a re-filter drops old notes."""
    index_path = run / "sheets" / "index.json"
    if not index_path.exists():
        return records
    shown = {row["listing_id"] for row in _read_json(index_path)}
    return [r for r in records if r.get("listing_id") in shown]


def _support(run: Path) -> Support:
    listings = {item["listing_id"]: item for item in _read_json(run / "listings.json")}
    records = _designs(run)
    _check(run, records, listings)
    records = _on_sheets(run, records)
    kept = [r for r in records if r.get("listing_id") in listings and not r.get("off_topic")]
    skipped = len(records) - len(kept)
    sys.stdout.write(f"{run.name}: {len(kept)} annotated listings, {skipped} off topic\n")

    scored = [(listings[r["listing_id"]], r) for r in kept]
    return {field: _field_support(field, scored) for field in FIELDS}


def _field_support(
    field: str, scored: list[tuple[dict[str, Any], dict[str, Any]]]
) -> dict[str, dict[str, float]]:
    hits: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for listing, record in scored:
        for tag in _tags(record, field):
            hits[tag][listing["shop_id"]].append(listing_score(listing))
    return {tag: _weigh(shops) for tag, shops in hits.items()}


def _is_gap(tag: str, field: str, supports: list[Support]) -> bool:
    general = supports[0][field]
    if len(supports) < MIN_RUNS_FOR_GAP or tag not in general:
        return False
    top = max(v["weight"] for v in general.values())
    strong = general[tag]["weight"] >= GAP_SHARE * top and general[tag]["shops"] >= GAP_MIN_SHOPS
    return strong and all(tag not in s[field] for s in supports[1:])


def _rows(field: str, names: list[str], supports: list[Support]) -> list[dict[str, Any]]:
    rows = []
    for tag in set().union(*(s[field] for s in supports)):
        cells = {name: s[field].get(tag) for name, s in zip(names, supports, strict=True)}
        total = sum(c["weight"] for c in cells.values() if c)
        rows.append(
            {"tag": tag, "total": round(total, 2), "gap": _is_gap(tag, field, supports), **cells}
        )
    return sorted(rows, key=lambda r: r["total"], reverse=True)


def _print_table(field: str, names: list[str], rows: list[dict[str, Any]]) -> None:
    lines = [
        f"\n## {field}\n",
        "| tag | " + " | ".join(names) + " | |",
        "|---|" + "---|" * len(names) + "---|",
    ]
    for row in rows[:TABLE_ROWS]:
        cells = [
            f"{row[n]['weight']:.1f} ({row[n]['shops']}sh)" if row.get(n) else "-" for n in names
        ]
        lines.append(
            f"| {row['tag']} | " + " | ".join(cells) + f" | {'gap' if row['gap'] else ''} |"
        )
    sys.stdout.write("\n".join(lines) + "\n")


def tally(runs: list[Path]) -> None:
    supports = [_support(run) for run in runs]
    names = [run.name for run in runs]
    report = {}
    for field in FIELDS:
        report[field] = _rows(field, names, supports)
        _print_table(field, names, report[field])
    out = runs[-1] / "tally.json"
    out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    sys.stdout.write(f"\nwrote {out}\n")


def _image_records(runs: list[Path]) -> dict[tuple[int, int], dict[str, Any]]:
    records: dict[tuple[int, int], dict[str, Any]] = {}
    for run in runs:
        for image in _read_json(run / "images.json"):
            records.setdefault((image["listing_id"], image["rank"]), image)
    return records


def refs(out: Path, runs: list[Path], picks: list[str]) -> None:
    records = _image_records(runs)
    out.mkdir(parents=True, exist_ok=True)
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        for number, pick in enumerate(picks, 1):
            listing_id, _, rank = pick.partition(":")
            key = (int(listing_id), int(rank or 1))
            if key not in records:
                sys.exit(f"no image {pick} in {', '.join(r.name for r in runs)}")
            response = client.get(records[key]["url_full"])
            response.raise_for_status()
            dest = out / f"ref-{number}-{key[0]}.jpg"
            dest.write_bytes(response.content)
            sys.stdout.write(f"{dest}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("sheets")
    make.add_argument("run", type=Path)
    make.add_argument("--top", type=int, default=60, help="listings to tile (default 60)")
    make.add_argument("--per-sheet", type=int, default=6, help="listings per sheet (default 6)")
    make.add_argument(
        "--match",
        default="",
        help="comma-separated words; keep only listings whose title contains one",
    )
    make.add_argument(
        "--exclude",
        default="",
        help="comma-separated words; drop listings whose title contains one",
    )
    count = sub.add_parser("tally")
    count.add_argument("runs", type=Path, nargs="+", help="general run first, then the niche run")
    grab = sub.add_parser("refs")
    grab.add_argument("out", type=Path, help="folder to save the reference images in")
    grab.add_argument("--runs", type=Path, nargs="+", required=True)
    grab.add_argument("picks", nargs="+", help="LISTING_ID or LISTING_ID:IMAGE_RANK")
    args = parser.parse_args()
    if args.command == "refs":
        refs(args.out, args.runs, args.picks)
    elif args.command == "sheets":
        words = [w.strip().lower() for w in args.match.split(",") if w.strip()]
        exclude = [w.strip().lower() for w in args.exclude.split(",") if w.strip()]
        sheets(args.run, args.top, args.per_sheet, words, exclude)
    else:
        tally(args.runs)


if __name__ == "__main__":
    main()

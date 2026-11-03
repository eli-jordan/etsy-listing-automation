"""Fetch details and analysis-size images for the listings found in browser searches.

    uv run python .claude/skills/etsy-research-proven-mockups/fetch_listings.py RUN_DIR [--images N]

Reads every RUN_DIR/pages/*.txt (the output of etsy-research's
extract_search_cards.js, one file per results page), looks each listing up
through the Etsy API, and writes:

    RUN_DIR/listings.json  one record per listing: details, shop stats, and
                           which searches/filters/badges surfaced it
    RUN_DIR/images.json    one record per downloaded image
    RUN_DIR/images/        the first N images of each listing at 570px wide
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "etsy-research"))
from etsy_api import WORKSPACE, Transport, _etsy_app_key_source

BATCH = 100


BADGES = {"B": "Bestseller", "P": "Popular now", "S": "Star Seller", "E": "Etsy's Pick"}
TOKEN = re.compile(r"(\d+)([a-zA-Z]*)")


def _parse_page(text: str) -> tuple[dict[str, str], list[tuple[int, str]]]:
    """Read one extract_search_cards.js result: a header line, then ID+flag tokens."""
    header, _, body = text.strip().partition("\n")
    search = dict(field.partition("=")[::2] for field in header.split("|"))
    cards = [(int(m[1]), m[2]) for m in TOKEN.finditer(body)]
    return search, cards


def _read_pages(run: Path) -> dict[int, dict[str, Any]]:
    found: dict[int, dict[str, Any]] = {}
    pages = sorted((run / "pages").glob("*.txt"))
    if not pages:
        sys.exit(f"no page files in {run / 'pages'}")
    for page in pages:
        _record_page(found, page.read_text(encoding="utf-8"))
    return found


def _record_page(found: dict[int, dict[str, Any]], text: str) -> None:
    search, cards = _parse_page(text)
    filters = [f for f in search.get("filters", "").split(",") if f]
    for position, (listing_id, flags) in enumerate(cards, 1):
        hit = found.setdefault(listing_id, {"hits": [], "badges": set(), "ad": False})
        hit["hits"].append({"q": search.get("q"), "filters": filters, "position": position})
        hit["badges"].update(BADGES[f] for f in flags if f in BADGES)
        hit["ad"] = hit["ad"] or "a" in flags


def _lookup(transport: Transport, ids: list[int]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for start in range(0, len(ids), BATCH):
        chunk = ",".join(str(i) for i in ids[start : start + BATCH])
        params = [("listing_ids", chunk), ("includes", "Images,Shop")]
        out.extend(transport.get("/v3/application/listings/batch", params=params).json()["results"])
    return out


def _download(client: httpx.Client, url: str, dest: Path) -> bool:
    if dest.exists():
        return True
    try:
        response = client.get(url)
        response.raise_for_status()
    except httpx.HTTPError:
        return False
    dest.write_bytes(response.content)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("run", type=Path)
    parser.add_argument("--images", type=int, default=6, help="images per listing (default 6)")
    args = parser.parse_args()
    run: Path = args.run

    found = _read_pages(run)
    details = _lookup(Transport(_etsy_app_key_source(WORKSPACE)), sorted(found))
    # SVG/PNG design files carry no garment photos.
    details = [item for item in details if item.get("listing_type") != "download"]

    listings: list[dict[str, Any]] = []
    images: list[dict[str, Any]] = []
    for item in details:
        hit = found[item["listing_id"]]
        shop = item.get("shop") or {}
        listings.append(
            {
                "listing_id": item["listing_id"],
                "shop_id": item["shop_id"],
                "shop_name": shop.get("shop_name"),
                "title": item["title"],
                "url": item["url"].split("?")[0],
                "num_favorers": item.get("num_favorers", 0),
                "taxonomy_id": item.get("taxonomy_id"),
                "tags": item.get("tags", []),
                "shop_review_average": shop.get("review_average"),
                "shop_review_count": shop.get("review_count"),
                "shop_sales": shop.get("transaction_sold_count"),
                "badges": sorted(hit["badges"]),
                "ad": hit["ad"],
                "hits": hit["hits"],
            }
        )
        ranked = sorted(item.get("images") or [], key=lambda i: i["rank"])[: args.images]
        images.extend(
            {
                "file": f"images/{item['listing_id']}_{image['rank']}.jpg",
                "listing_id": item["listing_id"],
                "shop_id": item["shop_id"],
                "rank": image["rank"],
                "url_570": image["url_570xN"],
                "url_full": image["url_fullxfull"],
                "full_width": image.get("full_width"),
                "full_height": image.get("full_height"),
            }
            for image in ranked
        )

    (run / "images").mkdir(exist_ok=True)
    with httpx.Client(timeout=30, follow_redirects=True) as client, ThreadPoolExecutor(8) as pool:
        ok = list(pool.map(lambda i: _download(client, i["url_570"], run / i["file"]), images))
    images = [i for i, good in zip(images, ok, strict=True) if good]

    (run / "listings.json").write_text(json.dumps(listings, indent=1), encoding="utf-8")
    (run / "images.json").write_text(json.dumps(images, indent=1), encoding="utf-8")
    sys.stdout.write(
        f"{len(found)} unique listings in the searches, {len(listings)} kept "
        f"(digital downloads dropped), "
        f"{len(images)} images ({ok.count(False)} failed)\n"
    )


if __name__ == "__main__":
    main()

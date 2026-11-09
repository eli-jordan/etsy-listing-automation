"""Look at a listing's real mockups: every gallery scene on one sheet, or one scene up close.

mockups.py sheet NAME --out DIR          writes DIR/sheet.jpg
mockups.py zoom NAME TEMPLATE COLOUR --out DIR   writes DIR/zoom-TEMPLATE-COLOUR.jpg
"""

import argparse
import io
import json
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw

TILE = 360
LABEL = 18
COLUMNS = 5
ZOOM_EDGE = 1400
WORKERS = 4


def say(text: str) -> None:
    sys.stdout.write(text + "\n")


def scene(url: str, name: str, template: str, colour: str) -> Image.Image:
    query = urllib.parse.urlencode({"template": template, "colour": colour, "scale": "full"})
    path = f"{url}/api/listings/{urllib.parse.quote(name)}/scene-preview?{query}"
    with urllib.request.urlopen(path, timeout=600) as response:
        return Image.open(io.BytesIO(response.read())).convert("RGB")


def tile(url: str, name: str, entry: dict[str, str]) -> Image.Image:
    image = scene(url, name, entry["template"], entry["colour"])
    image.thumbnail((TILE, TILE), Image.Resampling.LANCZOS)
    return image


def cmd_sheet(args: argparse.Namespace) -> None:
    detail_url = f"{args.url}/api/listings/{urllib.parse.quote(args.name)}"
    with urllib.request.urlopen(detail_url, timeout=60) as response:
        detail = json.load(response)
    entries = [m for m in detail["media"] if isinstance(m, dict)]
    with ThreadPoolExecutor(WORKERS) as pool:
        tiles = list(pool.map(lambda e: tile(args.url, args.name, e), entries))
    rows = -(-len(tiles) // COLUMNS)
    sheet = Image.new("RGB", (COLUMNS * TILE, rows * (TILE + LABEL)), "white")
    pen = ImageDraw.Draw(sheet)
    for index, (entry, image) in enumerate(zip(entries, tiles, strict=True)):
        x, y = (index % COLUMNS) * TILE, (index // COLUMNS) * (TILE + LABEL)
        sheet.paste(image, (x, y + LABEL))
        template = entry["template"].split("-", 1)[-1][:32]
        pen.text((x + 4, y + 3), f"{index + 1}. {template} / {entry['colour']}", fill="black")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    sheet.save(out / "sheet.jpg", quality=88)
    say(str(out / "sheet.jpg"))


def cmd_zoom(args: argparse.Namespace) -> None:
    image = scene(args.url, args.name, args.template, args.colour)
    image.thumbnail((ZOOM_EDGE, ZOOM_EDGE), Image.Resampling.LANCZOS)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"zoom-{args.template}-{args.colour}.jpg"
    image.save(path, quality=90)
    say(str(path))


def main() -> None:
    top = argparse.ArgumentParser(description=__doc__)
    top.add_argument("--url", default="http://127.0.0.1:8000")
    commands = top.add_subparsers(dest="command", required=True)
    sheet = commands.add_parser("sheet")
    sheet.add_argument("name")
    sheet.add_argument("--out", required=True)
    sheet.set_defaults(handler=cmd_sheet)
    zoom = commands.add_parser("zoom")
    for field in ("name", "template", "colour"):
        zoom.add_argument(field)
    zoom.add_argument("--out", required=True)
    zoom.set_defaults(handler=cmd_zoom)
    args = top.parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()

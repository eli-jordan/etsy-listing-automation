"""Rank a listing's shirt colours and draw the design on every one of them.

Prints JSON: the ranked colours and the three nearest finished listings. Writes
swatches.jpg to --out, every colour the garment sells in ranked order. Shirt
colours are measured once per garment from its profile's preview template.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import yaml
from PIL import Image, ImageDraw

Image.MAX_IMAGE_PIXELS = None
MIN_COLOURS = 3
TILE = 300
COLUMNS = 6
OPAQUE = 128
VISIBLE_DELTA = 25
MELT_DELTA = 15


def lab(rgb: Any) -> Any:
    pixels = np.asarray(rgb, np.float32).reshape(-1, 1, 3) / 255
    return cv2.cvtColor(pixels, cv2.COLOR_RGB2Lab).reshape(-1, 3)


def shirt_colours(root: Path, garment: str, profile: dict[str, Any]) -> Any:
    shades = profile["colors"]
    cache = root / ".cache" / "etsy-listing-create" / f"shirts-{garment}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf8"))
    folder = root / "mockup-templates" / profile["preview_template"]
    box = yaml.safe_load((folder / "template.yaml").read_text(encoding="utf8"))["bounding_box"]
    xs, ys = [p["x"] for p in box], [p["y"] for p in box]
    crop = (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)))
    shirts = {}
    for colour in shades:
        # The shortest match is the exact colour: "*-green" also matches "light-green".
        photo = min(folder.glob(f"*-{colour}.png"), key=lambda path: len(path.name))
        image = Image.open(photo).convert("RGB").crop(crop)
        shirts[colour] = [float(v) for v in np.median(np.asarray(image).reshape(-1, 3), axis=0)]
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(shirts), encoding="utf8")
    return shirts


def features(root: Path, ref: str, shirts: Any) -> Any:
    key = ref.replace("/", "_").replace(" ", "_")
    cache = root / ".cache" / "etsy-listing-create" / "features" / f"{key}.json"
    if cache.exists():
        return json.loads(cache.read_text(encoding="utf8"))
    image = Image.open(root / ref).convert("RGBA")
    image.thumbnail((420, 480), Image.Resampling.LANCZOS)
    pixels = np.asarray(image).astype(np.float32)
    mask = pixels[..., 3] > OPAQUE
    body = lab(pixels[..., :3][mask])
    ring = lab(
        pixels[..., :3][mask & ~cv2.erode(mask.astype(np.uint8), np.ones((5, 5))).astype(bool)]
    )
    result = {}
    for colour, rgb in shirts.items():
        shirt = lab(rgb)[0]
        delta = np.linalg.norm(body - shirt, axis=1)
        result[colour] = [
            float((delta >= VISIBLE_DELTA).mean()),
            float((delta < MELT_DELTA).mean()),
            float((np.linalg.norm(ring - shirt, axis=1) >= VISIBLE_DELTA).mean()),
            float(np.median(delta) / 100),
            float(np.median(np.abs(body[:, 0] - shirt[0])) / 100),
        ]
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(result), encoding="utf8")
    return result


def artwork(design: dict[str, str], colour: str, shades: dict[str, str]) -> str:
    if "default" in design:
        return design["default"]
    return design["on-dark" if shades[colour] == "dark" else "on-light"]


def fit(x: Any, y: Any) -> Any:
    x = np.hstack([x, np.ones((len(x), 1))])
    weights = np.zeros(x.shape[1])
    for _ in range(4000):
        predicted = 1 / (1 + np.exp(-x @ weights))
        weights -= 0.5 * (x.T @ (predicted - y) / len(y) + 0.001 * weights)
    return weights


def finished(root: Path, name: str) -> dict[str, Any]:
    found = {}
    for path in sorted((root / "listings").glob("*/listing.yaml")):
        document = yaml.safe_load(path.read_text(encoding="utf8"))
        title = (document.get("etsy") or {}).get("title")
        if path.parent.name != name and title and len(document["colors"]) >= MIN_COLOURS:
            found[path.parent.name] = document
    return found


def draw_sheet(root: Path, design: Any, shades: Any, ranked: list[Any], out: Path) -> None:
    chosen = ranked
    rows = -(-len(chosen) // COLUMNS)
    sheet = Image.new("RGB", (COLUMNS * TILE, rows * TILE), "white")
    pen = ImageDraw.Draw(sheet)
    art: dict[str, Any] = {}
    for index, item in enumerate(chosen):
        ref = artwork(design, item["colour"], shades)
        if ref not in art:
            image = Image.open(root / ref).convert("RGBA")
            image.thumbnail((TILE - 50, TILE - 50), Image.Resampling.LANCZOS)
            art[ref] = image
        x, y = (index % COLUMNS) * TILE, (index // COLUMNS) * TILE
        tile = Image.new("RGB", (TILE, TILE), tuple(int(v) for v in item["rgb"]))
        print_ = art[ref]
        tile.paste(print_, ((TILE - print_.width) // 2, 8), print_)
        sheet.paste(tile, (x, y))
        label = f"{index + 1}. {item['colour']} {item['score']:.2f}"
        pen.rectangle((x, y + TILE - 18, x + TILE, y + TILE), fill="white")
        pen.text((x + 5, y + TILE - 15), label, fill="black")
    sheet.save(out / "swatches.jpg", quality=88)


def rank(row: Any, past: dict[str, Any], document: Any, shades: Any, shirts: Any) -> list[Any]:
    x = np.array([row(d["design"], c) for d in past.values() for c in shades])
    y = np.array([float(c in d["colors"]) for d in past.values() for c in shades])
    weights = fit(x, y)
    ranked = []
    for colour in shades:
        values = row(document["design"], colour)
        score = 1 / (1 + np.exp(-(np.array([*values, 1.0]) @ weights)))
        ranked.append(
            {
                "colour": colour,
                "shade": shades[colour],
                "score": round(float(score), 3),
                "visible": round(values[0], 2),
                "rgb": shirts[colour],
            }
        )
    ranked.sort(key=lambda item: -item["score"])
    return ranked


def nearest_listings(row: Any, past: dict[str, Any], document: Any, shades: Any) -> list[Any]:
    mine = np.array([row(document["design"], c)[0] for c in shades])
    section = document["etsy"]["section"]
    distances = []
    for other, listing in past.items():
        theirs = np.array([row(listing["design"], c)[0] for c in shades])
        penalty = 0 if listing["etsy"].get("section") == section else 0.05
        distances.append((float(np.abs(mine - theirs).mean()) + penalty, other))
    distances.sort()
    return [
        {
            "listing": other,
            "colours": past[other]["colors"],
            "hero": past[other]["media"][0],
            "variation_images": past[other]["etsy"].get("variation_images"),
        }
        for _, other in distances[:3]
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--name", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    root, out = Path(args.root), Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    path = root / "listings" / args.name / "listing.yaml"
    document = yaml.safe_load(path.read_text(encoding="utf8"))
    garment = document["garment_profile"]
    profile_path = root / "garment-profiles" / f"{garment}.yaml"
    profile = yaml.safe_load(profile_path.read_text(encoding="utf8"))
    shades = profile["colors"]
    shirts = shirt_colours(root, garment, profile)
    past = finished(root, args.name)
    popularity = {c: sum(c in d["colors"] for d in past.values()) / len(past) for c in shades}

    def row(design: dict[str, str], colour: str) -> list[float]:
        feats = features(root, artwork(design, colour, shades), shirts)
        return [*feats[colour], popularity[colour]]

    ranked = rank(row, past, document, shades, shirts)
    precedents = nearest_listings(row, past, document, shades)
    draw_sheet(root, document["design"], shades, ranked, out)
    result = {"ranked": ranked, "precedents": precedents}
    (out / "colours.json").write_text(json.dumps(result, indent=1), encoding="utf8")
    lines = [
        f"{i + 1:2}. {c['colour']:12} {c['shade']:5} score {c['score']:.2f} "
        f"visible {c['visible']:.2f}"
        for i, c in enumerate(ranked)
    ]
    lines += ["", "Nearest finished listings:"]
    lines += [f"  {p['listing']}: {', '.join(p['colours'])}; hero {p['hero']}" for p in precedents]
    lines += ["", f"{out / 'swatches.jpg'} and {out / 'colours.json'}"]
    sys.stdout.write(chr(10).join(lines) + chr(10))


if __name__ == "__main__":
    main()

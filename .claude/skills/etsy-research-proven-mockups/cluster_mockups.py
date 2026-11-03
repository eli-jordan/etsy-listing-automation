# /// script
# requires-python = ">=3.12"
# dependencies = ["open_clip_torch", "torch", "opencv-python-headless", "numpy", "pillow"]
# ///
"""Group listing images that come from the same base mockup photo.

    uv run --script cluster_mockups.py cluster RUN_DIR
    uv run --script cluster_mockups.py download RUN_DIR CLUSTER NAME [--max N]

`cluster` reads RUN_DIR/images.json and listings.json (from fetch_listings.py):

1. Within each listing, images of the same photo (colour variants, re-crops)
   collapse into one representative, so later stages compare fewer images.
2. CLIP embeddings, with the chest blurred so the printed design doesn't
   dominate, propose each representative's nearest look-alikes from other shops.
3. SIFT keypoints outside the chest, matched under a crop/scale/shift model
   with RANSAC, confirm that a pair really shares one base photo.
4. Confirmed pairs join into clusters, ranked by distinct shops, then listings,
   then favourites.

It writes RUN_DIR/clusters.json, one contact sheet per cluster in
RUN_DIR/clusters/, and RUN_DIR/clusters/overview.jpg (one tile per cluster).

`download` saves the full-resolution images of one cluster, largest first and
one per listing, to RUN_DIR/final/<NN>-<NAME>/.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from collections import defaultdict
from collections.abc import Iterable
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import open_clip
import torch
from PIL import Image, ImageDraw, ImageFilter

CHEST = (0.28, 0.25, 0.72, 0.68)  # fraction of width/height where a tee's print usually sits
NEIGHBOURS = 12  # CLIP candidates checked per representative
MIN_SIMILARITY = 0.78  # CLIP floor for a candidate pair
MIN_INLIERS_SAME_LISTING = 15
MIN_INLIERS = 18
MIN_MATCHES = 8
RATIO = 0.75  # Lowe's ratio test
KNN = 2
SCALE_RANGE = (0.33, 3.0)  # crop/zoom allowed between two uses of one photo
MIN_SHOPS = 2
SIFT_FEATURES = 800
# Zero-shot CLIP labels: images closer to a chart prompt than a photo prompt are dropped.
CHART_PROMPTS = (
    "a size chart table of garment measurements",
    "a color chart of t-shirt color swatches with color names",
    "a grid of blank t-shirts in many colors showing the color options",
    "a text graphic with care instructions or how to order steps",
)
PHOTO_PROMPTS = (
    "a photo of a woman wearing a t-shirt",
    "a photo of a man wearing a t-shirt",
    "a photo of a person wearing a sweatshirt",
    "a flat lay photo of a t-shirt with props",
    "a photo of a t-shirt hanging on a hanger",
    "a photo of a family or couple wearing matching shirts",
    "a close-up photo of a printed graphic t-shirt",
)
CHART_PROBABILITY = 0.5
TILE = 220
LABEL = 28

Image_ = dict[str, Any]


def chest_box(w: int, h: int) -> tuple[int, int, int, int]:
    return int(w * CHEST[0]), int(h * CHEST[1]), int(w * CHEST[2]), int(h * CHEST[3])


class UnionFind:
    def __init__(self, n: int) -> None:
        self.parent = list(range(n))

    def find(self, i: int) -> int:
        while self.parent[i] != i:
            self.parent[i] = self.parent[self.parent[i]]
            i = self.parent[i]
        return i

    def union(self, a: int, b: int) -> None:
        self.parent[self.find(a)] = self.find(b)

    def groups(self) -> list[list[int]]:
        out: dict[int, list[int]] = defaultdict(list)
        for i in range(len(self.parent)):
            out[self.find(i)].append(i)
        return list(out.values())


class Matcher:
    """SIFT features outside the chest, cached; RANSAC inlier counts for pairs."""

    def __init__(self) -> None:
        self.sift = cv2.SIFT_create(nfeatures=SIFT_FEATURES)
        self.bf = cv2.BFMatcher(cv2.NORM_L2)
        self.cache: dict[Path, tuple[np.ndarray, np.ndarray]] = {}

    def features(self, path: Path) -> tuple[np.ndarray, np.ndarray]:
        if path not in self.cache:
            gray = cv2.imdecode(np.fromfile(str(path), np.uint8), cv2.IMREAD_GRAYSCALE)
            h, w = gray.shape
            mask = np.full((h, w), 255, np.uint8)
            x0, y0, x1, y1 = chest_box(w, h)
            mask[y0:y1, x0:x1] = 0
            keypoints, desc = self.sift.detectAndCompute(gray, mask)
            if desc is None:
                desc = np.zeros((0, 128), np.float32)
            points = np.float32([k.pt for k in keypoints])
            self.cache[path] = (points, desc.astype(np.float16))
        return self.cache[path]

    def inliers(self, a: Path, b: Path) -> int:
        pa, da = self.features(a)
        pb, db = self.features(b)
        if min(len(da), len(db)) < MIN_MATCHES:
            return 0
        pairs = self.bf.knnMatch(da.astype(np.float32), db.astype(np.float32), k=KNN)
        good = [p[0] for p in pairs if len(p) == KNN and p[0].distance < RATIO * p[1].distance]
        if len(good) < MIN_MATCHES:
            return 0
        src = pa[[m.queryIdx for m in good]]
        dst = pb[[m.trainIdx for m in good]]
        model, mask = cv2.estimateAffinePartial2D(
            src, dst, method=cv2.RANSAC, ransacReprojThreshold=5.0
        )
        if model is None:
            return 0
        scale = float(np.hypot(model[0, 0], model[1, 0]))
        return int(mask.sum()) if SCALE_RANGE[0] < scale < SCALE_RANGE[1] else 0


class Clip:
    """CLIP ViT-B-32: image embeddings, and text embeddings for zero-shot labels."""

    def __init__(self) -> None:
        self.model, _, self.preprocess = open_clip.create_model_and_transforms(
            "ViT-B-32", pretrained="laion2b_s34b_b79k"
        )
        self.model.eval()
        self.tokenizer = open_clip.get_tokenizer("ViT-B-32")

    def _load(self, path: Path, *, blur_chest: bool) -> torch.Tensor:
        image = Image.open(path).convert("RGB")
        if blur_chest:  # soften the printed design so scene, model and pose dominate
            box = chest_box(*image.size)
            image.paste(image.crop(box).filter(ImageFilter.GaussianBlur(25)), box)
        return self.preprocess(image)

    def images(self, paths: list[Path], *, blur_chest: bool) -> np.ndarray:
        out = []
        with torch.no_grad():
            for start in range(0, len(paths), 64):
                batch = [self._load(p, blur_chest=blur_chest) for p in paths[start : start + 64]]
                vectors = self.model.encode_image(torch.stack(batch))
                out.append(torch.nn.functional.normalize(vectors, dim=-1).numpy())
        return np.concatenate(out)

    def texts(self, prompts: tuple[str, ...]) -> np.ndarray:
        with torch.no_grad():
            vectors = self.model.encode_text(self.tokenizer(list(prompts)))
        return torch.nn.functional.normalize(vectors, dim=-1).numpy()


def is_chart(clip: Clip, paths: list[Path]) -> np.ndarray:
    """True where an image reads as a size/colour chart or text card rather than a photo."""
    vectors = clip.images(paths, blur_chest=False)
    prompts = clip.texts(CHART_PROMPTS + PHOTO_PROMPTS)
    logits = 100 * vectors @ prompts.T
    probs = np.exp(logits - logits.max(axis=1, keepdims=True))
    probs /= probs.sum(axis=1, keepdims=True)
    return probs[:, : len(CHART_PROMPTS)].sum(axis=1) > CHART_PROBABILITY


def collapse_listings(images: list[Image_], paths: list[Path], matcher: Matcher) -> list[list[int]]:
    """Group each listing's images of one photo; the first index is the lowest-rank image."""
    by_listing: dict[int, list[int]] = defaultdict(list)
    for i, image in enumerate(images):
        by_listing[image["listing_id"]].append(i)
    within = UnionFind(len(images))
    pairs = [
        (a, b)
        for members in by_listing.values()
        for x, a in enumerate(members)
        for b in members[x + 1 :]
    ]
    for a, b in pairs:
        if within.find(a) != within.find(b) and (
            matcher.inliers(paths[a], paths[b]) >= MIN_INLIERS_SAME_LISTING
        ):
            within.union(a, b)
    return [sorted(group, key=lambda i: images[i]["rank"]) for group in within.groups()]


def candidate_pairs(vectors: np.ndarray, shops: np.ndarray) -> set[tuple[int, int]]:
    similarity = vectors @ vectors.T
    similarity[shops[:, None] == shops[None, :]] = -1
    pairs: set[tuple[int, int]] = set()
    for a in range(len(vectors)):
        for b in np.argsort(-similarity[a])[:NEIGHBOURS]:
            if similarity[a, b] >= MIN_SIMILARITY:
                pairs.add((min(a, int(b)), max(a, int(b))))
    return pairs


def _count(found: Iterable[dict[str, Any]], test: Any) -> int:
    return sum(1 for item in found if test(item))


def _via(flag: str) -> Any:
    return lambda item: any(flag in h["filters"] for h in item["hits"])


def _member(group: list[int], images: list[Image_], listings: dict[int, dict[str, Any]]) -> Image_:
    image = images[group[0]]
    listing = listings[image["listing_id"]]
    return {
        **image,
        "shop_name": listing["shop_name"],
        "title": listing["title"],
        "listing_url": listing["url"],
        "num_favorers": listing["num_favorers"],
        "variants": [images[v]["file"] for v in group],
    }


def describe(
    members: list[list[int]], images: list[Image_], listings: dict[int, dict[str, Any]]
) -> dict[str, Any]:
    reps = [images[group[0]] for group in members]
    found = [listings[i] for i in sorted({r["listing_id"] for r in reps})]
    return {
        "shops": len({r["shop_id"] for r in reps}),
        "listings": len(found),
        "favorers": sum(item["num_favorers"] for item in found),
        "bestseller_badges": _count(found, lambda item: "Bestseller" in item["badges"]),
        "via_star_seller": _count(found, _via("is_star_seller")),
        "via_best_seller": _count(found, _via("is_best_seller")),
        "primary_image_uses": _count(reps, lambda r: r["rank"] == 1),
        "members": [_member(group, images, listings) for group in members],
    }


def _tile(path: Path, label: str) -> Image.Image:
    image = Image.open(path).convert("RGB")
    image.thumbnail((TILE, TILE))
    tile = Image.new("RGB", (TILE, TILE + LABEL), "white")
    tile.paste(image, ((TILE - image.width) // 2, 0))
    ImageDraw.Draw(tile).text((4, TILE + 4), label[:34], fill="black")
    return tile


def _sheet(tiles: list[Image.Image], columns: int, dest: Path) -> None:
    rows = (len(tiles) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * TILE, rows * (TILE + LABEL)), "white")
    for i, tile in enumerate(tiles):
        sheet.paste(tile, ((i % columns) * TILE, (i // columns) * (TILE + LABEL)))
    sheet.save(dest, quality=85)


def write_sheets(run: Path, clusters: list[dict[str, Any]]) -> None:
    out = run / "clusters"
    out.mkdir(exist_ok=True)
    for old in out.glob("*.jpg"):
        old.unlink()
    for item in clusters:
        members = sorted(item["members"], key=lambda m: -m["num_favorers"])[:24]
        tiles = [
            _tile(run / m["file"], f"{m['shop_name']} {m['num_favorers']}fav r{m['rank']}")
            for m in members
        ]
        _sheet(tiles, 6, out / f"{item['cluster']:02d}.jpg")
    overview = [
        _tile(
            run / c["members"][0]["file"],
            f"#{c['cluster']} {c['shops']}sh {c['listings']}li {c['favorers']}fav",
        )
        for c in clusters[:48]
    ]
    if overview:
        _sheet(overview, 8, out / "overview.jpg")


def write_dropped_sheet(run: Path, dropped: list[Image_]) -> None:
    """One sheet of the images the chart filter removed, for spot-checking it."""
    tiles = [_tile(run / i["file"], f"{i['listing_id']} r{i['rank']}") for i in dropped[:96]]
    if tiles:
        _sheet(tiles, 12, run / "clusters" / "dropped-charts.jpg")


def drop_charts(
    clip: Clip, variants: list[list[int]], paths: list[Path]
) -> tuple[list[list[int]], list[int]]:
    """Split off groups whose representative is a chart or text card."""
    charts = is_chart(clip, [paths[group[0]] for group in variants])
    kept = [group for group, chart in zip(variants, charts, strict=True) if not chart]
    dropped = [group[0] for group, chart in zip(variants, charts, strict=True) if chart]
    return kept, dropped


def verify(
    pairs: set[tuple[int, int]], paths: list[Path], matcher: Matcher
) -> tuple[UnionFind, int]:
    """Join the candidate pairs whose photos match geometrically."""
    joined = UnionFind(len(paths))
    confirmed = [
        (a, b) for a, b in sorted(pairs) if matcher.inliers(paths[a], paths[b]) >= MIN_INLIERS
    ]
    for a, b in confirmed:
        joined.union(a, b)
    return joined, len(confirmed)


def cluster(run: Path) -> None:
    images: list[Image_] = json.loads((run / "images.json").read_text(encoding="utf-8"))
    listing_rows = json.loads((run / "listings.json").read_text(encoding="utf-8"))
    listings = {item["listing_id"]: item for item in listing_rows}
    paths = [run / image["file"] for image in images]
    matcher = Matcher()

    variants = collapse_listings(images, paths, matcher)
    sys.stdout.write(f"{len(images)} images -> {len(variants)} after within-listing dedupe\n")

    clip = Clip()
    variants, dropped = drop_charts(clip, variants, paths)
    sys.stdout.write(f"{len(dropped)} size/colour charts and text cards dropped\n")

    reps = [group[0] for group in variants]
    vectors = clip.images([paths[i] for i in reps], blur_chest=True)
    pairs = candidate_pairs(vectors, np.array([images[i]["shop_id"] for i in reps]))
    sys.stdout.write(f"{len(pairs)} cross-shop candidate pairs\n")

    across, verified = verify(pairs, [paths[i] for i in reps], matcher)
    clusters = rank(
        [describe([variants[a] for a in group], images, listings) for group in across.groups()]
    )
    write_sheets(run, clusters)
    write_dropped_sheet(run, [images[i] for i in dropped])
    (run / "clusters.json").write_text(json.dumps(clusters, indent=1), encoding="utf-8")
    sys.stdout.write(f"{verified} verified pairs, {len(clusters)} clusters across 2+ shops\n")
    report(clusters)


def rank(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept = [c for c in clusters if c["shops"] >= MIN_SHOPS]
    kept.sort(key=lambda c: (-c["shops"], -c["listings"], -c["favorers"]))
    for number, item in enumerate(kept, 1):
        item["cluster"] = number
    return kept


def report(clusters: list[dict[str, Any]]) -> None:
    sys.stdout.write("cluster shops listings favs bestseller primary\n")
    for c in clusters[:40]:
        sys.stdout.write(
            f"{c['cluster']:>7} {c['shops']:>5} {c['listings']:>8} {c['favorers']:>4} "
            f"{c['bestseller_badges']:>10} {c['primary_image_uses']:>7}\n"
        )


def download(run: Path, number: int, name: str, limit: int) -> None:
    clusters = json.loads((run / "clusters.json").read_text(encoding="utf-8"))
    item = next((c for c in clusters if c["cluster"] == number), None)
    if item is None:
        sys.exit(f"no cluster {number}")
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    dest = run / "final" / f"{number:02d}-{slug}"
    dest.mkdir(parents=True, exist_ok=True)
    by_size = sorted(
        item["members"], key=lambda m: -((m["full_width"] or 0) * (m["full_height"] or 0))
    )
    chosen = list({m["listing_id"]: m for m in reversed(by_size)}.values())[::-1][:limit]
    for m in chosen:
        target = dest / f"{m['shop_name']}_{m['listing_id']}_{m['rank']}.jpg"
        request = urllib.request.Request(m["url_full"], headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            target.write_bytes(response.read())
    sys.stdout.write(f"{len(chosen)} images -> {dest}\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("cluster").add_argument("run", type=Path)
    get = sub.add_parser("download")
    get.add_argument("run", type=Path)
    get.add_argument("cluster", type=int)
    get.add_argument("name")
    get.add_argument("--max", type=int, default=4, help="images to keep, one per listing")
    args = parser.parse_args()
    if args.command == "cluster":
        cluster(args.run)
    else:
        download(args.run, args.cluster, args.name, args.max)


if __name__ == "__main__":
    main()

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
import math
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
# Zero-shot garment labels for --garment; an image takes the label of its best-matching prompt.
GARMENT_PROMPTS = {
    "tshirt": (
        "a photo of a person wearing a short sleeve t-shirt",
        "a flat lay photo of a short sleeve t-shirt",
        "a folded short sleeve t-shirt",
        "a short sleeve t-shirt on a hanger",
        "several short sleeve t-shirts laid out together",
        "a photo of a woman wearing an oversized short sleeve t-shirt",
        "a photo of a child wearing a short sleeve t-shirt",
    ),
    "sweatshirt": (
        "a photo of a person wearing a long sleeve crewneck sweatshirt",
        "a flat lay photo of a crewneck sweatshirt with long sleeves",
    ),
    "hoodie": ("a photo of a person wearing a hoodie", "a flat lay photo of a hoodie"),
    "long-sleeve": ("a photo of a person wearing a thin long sleeve t-shirt",),
    # No tank-top or child-shirt labels: on test data both captured adult tees.
    "baby": ("a baby bodysuit onesie",),
    "other": (
        "a photo of a mug",
        "a photo of a tote bag",
        "a photo of a hat",
        "a photo of jewelry",
    ),
}
TEMPLATE_SAMPLES = 2  # colour variants compared per template folder
TEMPLATE_WIDTH = 570  # match the listing images' analysis size
TEMPLATE_MEMBERS = 8  # members per cluster compared against templates
MIN_TEMPLATE_SIMILARITY = 0.7  # blank templates sit further from printed listings in CLIP
# Ranking. A listing scores log10(1+favourites) + VIEWS_WEIGHT*log10(1+views), plus
# bonuses for the Bestseller and Popular-now badges; a mockup scores the sum over its
# listings, so both how many listings use it and how well they perform count.
VIEWS_WEIGHT = 0.5
BESTSELLER_BONUS = 1.0
POPULAR_BONUS = 0.5
SAME_SHOP_WEIGHT = 0.25  # one shop reusing its own mockup is weaker evidence
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


def garment_labels(clip: Clip, paths: list[Path]) -> list[str]:
    """Each image's garment, by its best-matching GARMENT_PROMPTS prompt."""
    names = [name for name, prompts in GARMENT_PROMPTS.items() for _ in prompts]
    prompts = tuple(p for group in GARMENT_PROMPTS.values() for p in group)
    best = (clip.images(paths, blur_chest=False) @ clip.texts(prompts).T).argmax(axis=1)
    return [names[i] for i in best]


def keep_garment(
    clip: Clip, variants: list[list[int]], paths: list[Path], garment: str
) -> tuple[list[list[int]], list[tuple[int, str]]]:
    """Split off groups whose representative shows another garment."""
    labels = garment_labels(clip, [paths[group[0]] for group in variants])
    kept = [group for group, label in zip(variants, labels, strict=True) if label == garment]
    dropped = [
        (group[0], label) for group, label in zip(variants, labels, strict=True) if label != garment
    ]
    return kept, dropped


def template_samples(templates: Path, run: Path) -> list[tuple[str, Path]]:
    """A few colour variants per template folder, resized to the analysis width."""
    out_dir = run / "templates"
    out_dir.mkdir(exist_ok=True)
    samples = []
    for folder in sorted(p for p in templates.iterdir() if p.is_dir()):
        for source in sorted(folder.glob("*.png"))[:TEMPLATE_SAMPLES]:
            target = out_dir / f"{folder.name}__{source.stem}.jpg"
            if not target.exists():
                image = Image.open(source).convert("RGB")
                image.thumbnail((TEMPLATE_WIDTH, TEMPLATE_WIDTH * 3))
                image.save(target, quality=90)
            samples.append((folder.name, target))
    return samples


def match_templates(
    clusters: list[dict[str, Any]], run: Path, templates: Path, clip: Clip, matcher: Matcher
) -> None:
    """Set cluster["template"] to the workspace template a cluster's photo already is."""
    samples = template_samples(templates, run)
    if not samples:
        return
    sample_vectors = clip.images([path for _, path in samples], blur_chest=True)
    for item in clusters:
        members = [run / m["file"] for m in item["members"][:TEMPLATE_MEMBERS]]
        similarity = clip.images(members, blur_chest=True) @ sample_vectors.T
        item["template"] = next(
            (
                samples[t][0]
                for m, t in zip(*np.nonzero(similarity >= MIN_TEMPLATE_SIMILARITY), strict=True)
                if matcher.inliers(members[m], samples[t][1]) >= MIN_INLIERS
            ),
            None,
        )


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
        "views": listing.get("views", 0),
        "listing_score": listing_score(listing),
        "variants": [images[v]["file"] for v in group],
    }


def is_bestseller(listing: dict[str, Any]) -> bool:
    """Badge on the card, or surfaced by the is_best_seller filter (cards show one badge only)."""
    return "Bestseller" in listing["badges"] or _via("is_best_seller")(listing)


def listing_score(listing: dict[str, Any]) -> float:
    """How well one listing performs: favourites and views on a log scale, plus badges."""
    return round(
        math.log10(1 + listing["num_favorers"])
        + VIEWS_WEIGHT * math.log10(1 + listing.get("views", 0))
        + BESTSELLER_BONUS * is_bestseller(listing)
        + POPULAR_BONUS * ("Popular now" in listing["badges"]),
        2,
    )


def mockup_score(found: list[dict[str, Any]]) -> float:
    """Sum of listing scores; each shop's best listing counts in full, its others at a discount."""
    by_shop: dict[int, list[float]] = defaultdict(list)
    for listing in found:
        by_shop[listing["shop_id"]].append(listing_score(listing))
    total = 0.0
    for scores in by_shop.values():
        best, *rest = sorted(scores, reverse=True)
        total += best + SAME_SHOP_WEIGHT * sum(rest)
    return round(total, 2)


def describe(
    members: list[list[int]], images: list[Image_], listings: dict[int, dict[str, Any]]
) -> dict[str, Any]:
    reps = [images[group[0]] for group in members]
    found = [listings[i] for i in sorted({r["listing_id"] for r in reps})]
    return {
        "score": mockup_score(found),
        "shops": len({r["shop_id"] for r in reps}),
        "listings": len(found),
        "favorers": sum(item["num_favorers"] for item in found),
        "views": sum(item.get("views", 0) for item in found),
        "bestsellers": _count(found, is_bestseller),
        "popular_now": _count(found, lambda item: "Popular now" in item["badges"]),
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
    for item in clusters:
        members = sorted(item["members"], key=lambda m: -m["listing_score"])[:24]
        tiles = [
            _tile(run / m["file"], f"{m['shop_name']} s{m['listing_score']} {m['num_favorers']}fav")
            for m in members
        ]
        _sheet(tiles, 6, out / f"{item['cluster']:02d}.jpg")
    overview = [
        _tile(
            run / c["members"][0]["file"],
            f"#{c['cluster']} score {c['score']} {c['shops']}sh {c['listings']}li",
        )
        for c in clusters[:48]
    ]
    if overview:
        _sheet(overview, 8, out / "overview.jpg")


def write_dropped_sheet(run: Path, dropped: list[tuple[Image_, str]], name: str) -> None:
    """One sheet of the images a filter removed, for spot-checking it."""
    tiles = [_tile(run / i["file"], f"{label} {i['listing_id']}") for i, label in dropped[:96]]
    if tiles:
        _sheet(tiles, 12, run / "clusters" / name)


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


def filter_images(
    run: Path, images: list[Image_], variants: list[list[int]], clip: Clip, garment: str | None
) -> list[list[int]]:
    """Drop charts, then (with --garment) other garments; sheet what each filter removed."""
    paths = [run / image["file"] for image in images]
    (run / "clusters").mkdir(exist_ok=True)
    for old in (run / "clusters").glob("*.jpg"):
        old.unlink()
    variants, charts = drop_charts(clip, variants, paths)
    write_dropped_sheet(run, [(images[i], "chart") for i in charts], "dropped-charts.jpg")
    sys.stdout.write(f"{len(charts)} size/colour charts and text cards dropped\n")
    if garment:
        variants, others = keep_garment(clip, variants, paths, garment)
        dropped = [(images[i], label) for i, label in others]
        write_dropped_sheet(run, dropped, "dropped-garments.jpg")
        sys.stdout.write(f"{len(others)} images of garments other than {garment} dropped\n")
    return variants


def split_owned(
    groups: list[dict[str, Any]],
    run: Path,
    templates: Path | None,
    clip: Clip,
    matcher: Matcher,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Keep 2+-shop groups; rank those the user has no template for, set aside those they do."""
    groups = [c for c in groups if c["shops"] >= MIN_SHOPS]
    if templates:
        match_templates(groups, run, templates, clip, matcher)
    owned = [c for c in groups if c.get("template")]
    return rank([c for c in groups if not c.get("template")]), owned


def cluster(run: Path, garment: str | None, templates: Path | None) -> None:
    images: list[Image_] = json.loads((run / "images.json").read_text(encoding="utf-8"))
    listing_rows = json.loads((run / "listings.json").read_text(encoding="utf-8"))
    listings = {item["listing_id"]: item for item in listing_rows}
    paths = [run / image["file"] for image in images]
    matcher = Matcher()

    variants = collapse_listings(images, paths, matcher)
    sys.stdout.write(f"{len(images)} images -> {len(variants)} after within-listing dedupe\n")

    clip = Clip()
    variants = filter_images(run, images, variants, clip, garment)

    reps = [group[0] for group in variants]
    vectors = clip.images([paths[i] for i in reps], blur_chest=True)
    pairs = candidate_pairs(vectors, np.array([images[i]["shop_id"] for i in reps]))
    sys.stdout.write(f"{len(pairs)} cross-shop candidate pairs\n")

    across, verified = verify(pairs, [paths[i] for i in reps], matcher)
    groups = [describe([variants[a] for a in group], images, listings) for group in across.groups()]
    clusters, owned = split_owned(groups, run, templates, clip, matcher)
    write_sheets(run, clusters)
    (run / "clusters.json").write_text(json.dumps(clusters, indent=1), encoding="utf-8")
    (run / "owned-templates.json").write_text(json.dumps(owned, indent=1), encoding="utf-8")
    sys.stdout.write(f"{verified} verified pairs, {len(clusters)} clusters across 2+ shops\n")
    for c in owned:
        sys.stdout.write(
            f"excluded, already a workspace template: {c['template']} ({c['shops']} shops)\n"
        )
    report(clusters)


def rank(clusters: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept = list(clusters)
    kept.sort(key=lambda c: (-c["score"], -c["shops"]))
    for number, item in enumerate(kept, 1):
        item["cluster"] = number
    return kept


def report(clusters: list[dict[str, Any]]) -> None:
    sys.stdout.write("cluster score shops listings  favs   views bestsell popular primary\n")
    for c in clusters[:40]:
        sys.stdout.write(
            f"{c['cluster']:>7} {c['score']:>5} {c['shops']:>5} {c['listings']:>8} "
            f"{c['favorers']:>5} {c['views']:>7} {c['bestsellers']:>8} {c['popular_now']:>7} "
            f"{c['primary_image_uses']:>7}\n"
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
    group = sub.add_parser("cluster")
    group.add_argument("run", type=Path)
    group.add_argument(
        "--garment", choices=sorted(GARMENT_PROMPTS), help="keep only images of this garment"
    )
    group.add_argument(
        "--exclude-templates",
        type=Path,
        help="mockup-templates directory; groups matching a template there are set aside",
    )
    get = sub.add_parser("download")
    get.add_argument("run", type=Path)
    get.add_argument("cluster", type=int)
    get.add_argument("name")
    get.add_argument("--max", type=int, default=4, help="images to keep, one per listing")
    args = parser.parse_args()
    if args.command == "cluster":
        cluster(args.run, args.garment, args.exclude_templates)
    else:
        download(args.run, args.cluster, args.name, args.max)


if __name__ == "__main__":
    main()

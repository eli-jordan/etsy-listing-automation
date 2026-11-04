"""Comfort Colors 1717 recolour runs for a mockup template photo.

prepare: check the source is 2048x2048, start a run directory and write one
Codex brief per colour.
assemble: turn the generated photos in out/ into an ingest-ready export
(`{scene} - {Colour}.png` + `{scene} - {Colour} - Text.png`) and review sheets.

Run from the repo root: uv run python .claude/skills/recolour-mockup-template/recolour.py --help
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

SKILL_DIR = Path(__file__).resolve().parent
OVERLAY_DIR = SKILL_DIR / "overlays"
BRIEF_TEMPLATE = SKILL_DIR / "codex-brief.md"
SIZE = 2048
# The installed Upscayl app's engine and models. Standard was chosen over LANCZOS
# and High Fidelity in the umbrella review (2026-11-04).
UPSCAYL_DIR = Path(r"C:\Program Files\Upscayl\resources")
UPSCAYL_MODEL = "upscayl-standard-4x"
ANALYSIS_SIZE = 512
CHANGE_THRESHOLD = 40  # max per-channel difference (0-255) that counts as changed
# At ANALYSIS_SIZE: a 4px edge band is 16px at 2048; specks under 3px are noise.
EDGE_BAND = 4
SPECK_SIZE = 3
GARMENT_CONSENSUS = 0.5  # share of recolours that must change a pixel to call it garment
MAX_DRIFT_PCT = 1.0  # a recolour that changed more of the frame outside the shirt is retried
# The pilot: one light and one dark colour, generated and reviewed before the rest.
PILOT_LIGHT_CHOICES = ("White", "Ivory")
PILOT_DARK_CHOICES = ("Black", "Pepper")
PILOT_NOTES_HEADING = "## Pilot review"
REFERENCE_MASK = "garment-reference.png"  # the approved pilot's shirt outline
TILE = 512  # pilot review tiles, at full 2048 resolution
TILE_MARGIN = 128
MIN_REGION_SHARE = 0.02  # outline regions under 2% of the largest are noise, not shirt
# Shading inside the outline: lighting and folds must follow the source whatever the colour.
SRGB_KNEE = 0.04045  # where the sRGB transfer curve stops being linear
FABRIC_THRESHOLD = 60  # change from the source that marks fabric, not hair over it
LIGHT_SIGMA = 10  # broad lighting, at ANALYSIS_SIZE
FOLD_SIGMA = 2  # folds and creases: detail finer than the lighting, coarser than weave
MIN_LIGHT_R = 0.5  # real recolours scored 0.64+; relit or flattened shirts 0.05-0.10
MIN_FOLDS_R = 0.3  # real recolours scored 0.34+; shifted or flattened folds below 0
SHADING_MISMATCH_Z = 1.5  # per-pixel difference, in standard deviations, drawn on the map
SHIRT_GROW = 12  # px at 2048 the approved outline grows before blending a recolour in
SHIRT_FEATHER = 6
# Cleaning a source: the generator's edit replaces only the areas it changed.
CLEAN_CHANGE = 40  # blurred per-channel change that marks an edited area
CLEAN_MIN_AREA = 4000  # px at 2048; smaller changes are regeneration noise, not an edit
CLEAN_GROW = 32  # px each patch grows past the edited area's convex hull
CLEAN_PAD = 64
CLEAN_RING = 41  # px band either side of a patch edge used to compare inside with outside
MAX_ECHO_R = 0.2  # the cleaned patch still follows the removed item's edges
MAX_TEXTURE_SHAPE_R = 0.2  # the patch's grain traces the removed item's shape
TEXTURE_RATIO_RANGE = (0.6, 1.6)  # patch grain against the surrounding original's
THUMB = 460
SHEET_COLUMNS = 4
SHEET_ROWS = 3

# Comfort Colors 1717 garment colours. The keys are the exact colour names the
# Text overlays carry and the export filenames use.
COLOURS: dict[str, str] = {
    "Bay": "#9DABA9",
    "Berry": "#890957",
    "Black": "#000000",
    "Blossom": "#EDC0CA",
    "Blue Jean": "#125D8F",
    "Blue Spruce": "#00493E",
    "Brick": "#A72D37",
    "Butter": "#F4DB8D",
    "Chalky Mint": "#5EB9B5",
    "Chambray": "#BBD3DD",
    "Chili": "#AC1358",
    "Crimson": "#A61440",
    "Crunchberry": "#ED5783",
    "Espresso": "#5E3C32",
    "Flo Blue": "#3B6AA7",
    "Graphite": "#001524",
    "Grey": "#64645B",
    "Island Reef": "#A0D6D7",
    "Ivory": "#E1D0A6",
    "Lagoon Blue": "#32C1DD",
    "Light Green": "#286D4A",
    "Moss": "#1B3324",
    "Mustard": "#F1CE15",
    "Navy": "#001C3D",
    "Neon Pink": "#DA1683",
    "Orchid": "#C8B2D6",
    "Pepper": "#141F28",
    "Red": "#CC1C2C",
    "Sapphire": "#008CCC",
    "Violet": "#7074B6",
    "Watermelon": "#EE3F4F",
    "White": "#FFFFFF",
    "Yam": "#C55624",
}


def say(text: str) -> None:
    sys.stdout.write(text + "\n")


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def resolve_colour(name: str) -> str:
    for colour in COLOURS:
        if slugify(colour) == slugify(name):
            return colour
    raise SystemExit(f"Unknown colour '{name}'. Known: {', '.join(COLOURS)}")


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)


def rgb_to_hex(rgb: np.ndarray) -> str:
    r, g, b = (round(float(c)) for c in rgb)
    return f"#{r:02X}{g:02X}{b:02X}"


# --- prepare -------------------------------------------------------------


def check_source(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"Source image not found: {path}")
    with Image.open(path) as image:
        size = image.size
    if size != (SIZE, SIZE):
        raise SystemExit(f"Source image is {size[0]}x{size[1]}; it must be {SIZE}x{SIZE}.")


def pilot_colours(source_colour: str | None) -> list[str]:
    """One light and one dark colour, skipping the colour the source already is."""
    return [
        next(c for c in choices if c != source_colour)
        for choices in (PILOT_LIGHT_CHOICES, PILOT_DARK_CHOICES)
    ]


def brief_path(run_dir: Path, colour: str) -> Path:
    return run_dir / "briefs" / f"{slugify(colour)}.md"


def write_brief(run_dir: Path, colour: str, template: str) -> Path:
    slug = slugify(colour)
    brief = template.format(
        colour=colour,
        hex=COLOURS[colour],
        source=run_dir / "source.png",
        output=run_dir / "out" / f"{slug}.png",
    )
    path = run_dir / "briefs" / f"{slug}.md"
    path.write_text(brief, encoding="utf-8")
    return path


def prepare(args: argparse.Namespace) -> None:
    source = Path(args.source)
    check_source(source)
    run_dir = Path(args.run_dir)
    if (run_dir / "run.json").exists():
        raise SystemExit(f"{run_dir} already holds a run; pick another --run-dir.")
    for sub in ("briefs", "out"):
        (run_dir / sub).mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        image.save(run_dir / "source.png")

    source_colour = resolve_colour(args.source_colour) if args.source_colour else None
    if source_colour:
        shutil.copyfile(run_dir / "source.png", run_dir / "out" / f"{slugify(source_colour)}.png")

    template = BRIEF_TEMPLATE.read_text(encoding="utf-8")
    briefs = [
        str(write_brief(run_dir, colour, template)) for colour in COLOURS if colour != source_colour
    ]
    pilots = pilot_colours(source_colour)
    meta = {
        "scene": args.scene,
        "source": str(source),
        "source_colour": source_colour,
        "pilots": pilots,
    }
    (run_dir / "run.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    say(f"Run directory: {run_dir}")
    say("Pilot briefs:\n" + "\n".join(str(brief_path(run_dir, c)) for c in pilots))
    say(f"{len(briefs) - len(pilots)} other briefs, launched after the pilot is approved.")


# --- assemble ------------------------------------------------------------


@dataclass
class Result:
    colour: str
    path: Path
    pixels: np.ndarray  # ANALYSIS_SIZE square RGB, float32
    changed: np.ndarray  # bool mask of pixels that differ from the source
    drift: float = 0.0
    drift_map: np.ndarray | None = None  # bool mask of drift pixels, set by score
    measured: str | None = None
    shading_ref: str | None = None  # what the shading was compared with, set by score_shading
    light_r: float | None = None
    folds_r: float | None = None
    shading_map: np.ndarray | None = None  # bool mask of mismatched shading


def load_rgb(path: Path, size: int) -> np.ndarray:
    with Image.open(path) as image:
        small = image.convert("RGB").resize((size, size), Image.Resampling.LANCZOS)
    return np.asarray(small, dtype=np.float32)


def check_square(path: Path) -> str | None:
    with Image.open(path) as image:
        width, height = image.size
    if abs(width - height) > max(width, height) * 0.01:
        return f"{path.name} is {width}x{height}, not square; regenerate it"
    return None


def load_results(run_dir: Path, source: np.ndarray) -> tuple[list[Result], list[str]]:
    results: list[Result] = []
    problems: list[str] = []
    for colour in COLOURS:
        path = run_dir / "out" / f"{slugify(colour)}.png"
        if not path.is_file():
            problems.append(f"{colour}: missing {path.name}")
            continue
        problem = check_square(path)
        if problem:
            problems.append(f"{colour}: {problem}")
            continue
        pixels = load_rgb(path, ANALYSIS_SIZE)
        changed = np.abs(pixels - source).max(axis=2) > CHANGE_THRESHOLD
        results.append(Result(colour, path, pixels, changed))
    return results, problems


def drift_mask(changed: np.ndarray, garment: np.ndarray) -> np.ndarray:
    """Pixels the generator changed outside the garment and its edge band.

    The band absorbs hair strands and anti-aliased edges, which blend with the
    new shirt colour and change more against a dark shirt; without it, dark
    colours measured 1-1.5% with nothing moved. Opening drops isolated specks
    such as a twinkling light, so what remains is a real change of shape.
    """
    band = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * EDGE_BAND + 1,) * 2)
    near_garment = cv2.dilate(garment.astype(np.uint8), band) > 0
    outside = (changed & ~near_garment).astype(np.uint8)
    speck = np.ones((SPECK_SIZE, SPECK_SIZE), np.uint8)
    return cv2.morphologyEx(outside, cv2.MORPH_OPEN, speck) > 0


def score(results: list[Result], reference: np.ndarray | None) -> None:
    """Drift and measured shirt colour, against the garment outline.

    The outline is the approved pilot's (`reference`), checked by eye against
    the source. Without one it falls back to wherever most recolours changed
    the source, which a mistake every colour shares (a sleeve grown behind the
    hair) passes as shirt. Changes outside the outline (see drift_mask) are
    drift: the generator moved the scene, the model or the shirt's outline.
    """
    if not results:
        return
    if reference is None:
        reference = np.mean([r.changed for r in results], axis=0) >= GARMENT_CONSENSUS
    garment = reference
    for result in results:
        result.drift_map = drift_mask(result.changed, garment)
        result.drift = float(result.drift_map.mean() * 100)
        if garment.any():
            result.measured = rgb_to_hex(np.median(result.pixels[garment], axis=0))


def upscayl_binary() -> Path:
    binary = UPSCAYL_DIR / "bin" / "upscayl-bin.exe"
    if not binary.is_file():
        raise SystemExit(f"Upscayl not found at {binary}; install Upscayl or pass --no-upscale.")
    return binary


def upscaled(run_dir: Path, path: Path) -> Path:
    """The generator's photo, 4x upscaled with Upscayl Standard, cached beside out/.

    A cached upscale older than its source photo (a redone colour) is rebuilt.
    """
    cache = run_dir / "upscaled" / path.name
    if cache.is_file() and cache.stat().st_mtime >= path.stat().st_mtime:
        return cache
    cache.parent.mkdir(exist_ok=True)
    command = [
        str(upscayl_binary()),
        *("-i", str(path), "-o", str(cache), "-s", "4", "-f", "png"),
        *("-n", UPSCAYL_MODEL, "-m", str(UPSCAYL_DIR / "models")),
    ]
    subprocess.run(command, check=True, capture_output=True)
    return cache


def full_size(run_dir: Path, path: Path, *, upscale: bool) -> Image.Image:
    with Image.open(path) as image:
        native = image.size == (SIZE, SIZE)
    source = upscaled(run_dir, path) if upscale and not native else path
    with Image.open(source) as image:
        return image.convert("RGB").resize((SIZE, SIZE), Image.Resampling.LANCZOS)


def shirt_alpha(reference: np.ndarray) -> np.ndarray:
    """The approved outline at full size, grown and feathered so the new shirt's
    edge blends into the source instead of cutting against it."""
    full = cv2.resize(reference.astype(np.uint8), (SIZE, SIZE), interpolation=cv2.INTER_NEAREST)
    grow = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * SHIRT_GROW + 1,) * 2)
    grown = cv2.dilate(full, grow).astype(np.float32)
    return cv2.GaussianBlur(grown, (0, 0), SHIRT_FEATHER)[..., None]


def composite_shirt(source: np.ndarray, recolour: Image.Image, alpha: np.ndarray) -> Image.Image:
    """Only the shirt comes from the generator; face, hair, hands and background
    keep the source's own pixels, which no regeneration can match for sharpness."""
    blended = source * (1 - alpha) + np.asarray(recolour, np.float32) * alpha
    return Image.fromarray(np.clip(blended, 0, 255).astype(np.uint8))


def export(run_dir: Path, scene: str, results: list[Result], *, upscale: bool) -> Path:
    export_dir = run_dir / "export"
    if export_dir.exists():
        shutil.rmtree(export_dir)
    export_dir.mkdir()
    shutil.copyfile(run_dir / "source.png", export_dir / f"{scene} - Source Image.png")
    reference = load_reference(run_dir)
    alpha = None if reference is None else shirt_alpha(reference)
    with Image.open(run_dir / "source.png") as image:
        source = np.asarray(image.convert("RGB").resize((SIZE, SIZE)), np.float32)
    for result in results:
        full = full_size(run_dir, result.path, upscale=upscale)
        if alpha is not None:
            full = composite_shirt(source, full, alpha)
        full.save(export_dir / f"{scene} - {result.colour}.png")
        shutil.copyfile(
            OVERLAY_DIR / f"{result.colour}.png",
            export_dir / f"{scene} - {result.colour} - Text.png",
        )
    return export_dir


def draw_cell(sheet: Image.Image, result: Result, thumb: Image.Image, xy: tuple[int, int]) -> None:
    x, y = xy
    font = ImageFont.load_default(size=18)
    sheet.paste(thumb.resize((THUMB, THUMB), Image.Resampling.LANCZOS), (x, y))
    draw = ImageDraw.Draw(sheet)
    label_y = y + THUMB + 6
    draw.rectangle((x, label_y, x + 40, label_y + 40), fill=COLOURS[result.colour], outline="#888")
    if result.measured:
        draw.rectangle(
            (x + 46, label_y, x + 86, label_y + 40), fill=result.measured, outline="#888"
        )
    text = (
        f"{result.colour}  target {COLOURS[result.colour]}\n"
        f"measured {result.measured or 'n/a'}  drift {result.drift:.1f}%"
    )
    if result.light_r is not None and result.folds_r is not None:
        text += f"\nlighting {result.light_r:.2f}  folds {result.folds_r:.2f}"
    draw.multiline_text((x + 96, label_y), text, fill="black", font=font)


def review_sheets(run_dir: Path, results: list[Result], export_dir: Path, scene: str) -> list[Path]:
    """Tile the exported photos, the composites that get ingested, with each
    colour's figures."""
    review_dir = run_dir / "review"
    review_dir.mkdir(exist_ok=True)
    per_sheet = SHEET_COLUMNS * SHEET_ROWS
    cell_w, cell_h = THUMB + 20, THUMB + 92
    sheets = []
    for start in range(0, len(results), per_sheet):
        chunk = results[start : start + per_sheet]
        rows = -(-len(chunk) // SHEET_COLUMNS)
        sheet = Image.new("RGB", (cell_w * SHEET_COLUMNS, cell_h * rows), "white")
        for index, result in enumerate(chunk):
            row, column = divmod(index, SHEET_COLUMNS)
            with Image.open(export_dir / f"{scene} - {result.colour}.png") as exported:
                thumb = exported.convert("RGB")
            draw_cell(sheet, result, thumb, (column * cell_w + 10, row * cell_h + 10))
        path = review_dir / f"sheet-{start // per_sheet + 1:02d}.jpg"
        sheet.save(path, quality=90)
        sheets.append(path)
    return sheets


# --- clean ---------------------------------------------------------------


def load_square(path: Path) -> np.ndarray:
    problem = check_square(path)
    if problem:
        raise SystemExit(problem)
    with Image.open(path) as image:
        return np.asarray(image.convert("RGB").resize((SIZE, SIZE), Image.Resampling.LANCZOS))


def edited_patches(original: np.ndarray, generated: np.ndarray) -> list[np.ndarray]:
    """One patch per area the generator edited: its convex hull, grown, so the
    patch edge never traces the removed item's shape."""
    change = np.abs(generated.astype(np.int16) - original).max(axis=2).astype(np.float32)
    edited = (cv2.GaussianBlur(change, (0, 0), 6) > CLEAN_CHANGE).astype(np.uint8)
    count, labels, stats, _ = cv2.connectedComponentsWithStats(edited)
    grow = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * CLEAN_GROW + 1,) * 2)
    patches = []
    for label in range(1, count):
        if stats[label, cv2.CC_STAT_AREA] < CLEAN_MIN_AREA:
            continue
        hull = np.zeros((SIZE, SIZE), np.uint8)
        points = cv2.findNonZero((labels == label).astype(np.uint8))
        cv2.fillConvexPoly(hull, cv2.convexHull(points), 1)
        patches.append(cv2.dilate(hull, grow) > 0)
    return patches


def clone_patches(
    original: np.ndarray, generated: np.ndarray, patches: list[np.ndarray]
) -> np.ndarray:
    """Poisson-blend each patch from the generated image onto the original, so
    the patch's tone meets the original seamlessly at its edge. The padding is
    the generated image's, so a patch on the frame edge borrows clean values."""
    pad = CLEAN_PAD
    source = cv2.copyMakeBorder(generated, pad, pad, pad, pad, cv2.BORDER_REFLECT)
    canvas = source.copy()
    canvas[pad:-pad, pad:-pad] = original
    for patch in patches:
        mask = np.zeros(canvas.shape[:2], np.uint8)
        mask[pad:-pad, pad:-pad] = patch * 255
        if patch[0].any() or patch[-1].any() or patch[:, 0].any() or patch[:, -1].any():
            mask = cv2.dilate(mask, np.ones((2 * pad + 1,) * 2, np.uint8))
        mask[[0, -1], :] = 0
        mask[:, [0, -1]] = 0
        x, y, w, h = cv2.boundingRect(mask)
        canvas = cv2.seamlessClone(source, canvas, mask, (x + w // 2, y + h // 2), cv2.NORMAL_CLONE)
    return canvas[pad:-pad, pad:-pad]


def grain(values: np.ndarray) -> np.ndarray:
    values = values.astype(np.float32)
    return values - cv2.GaussianBlur(values, (0, 0), 1.5)


def ring_outside(patch: np.ndarray) -> np.ndarray:
    grown = cv2.dilate(patch.astype(np.uint8), np.ones((CLEAN_RING, CLEAN_RING), np.uint8))
    return grown.astype(bool) & ~patch


def match_grain(cleaned: np.ndarray, original: np.ndarray, patches: list[np.ndarray]) -> np.ndarray:
    """Top up each smooth generated patch with fine grain to the level of the
    original around it; a smooth patch on grainy fabric reads as a shadow."""
    rng = np.random.default_rng(2026)
    result = cleaned.astype(np.float32)
    for patch in patches:
        want = grain(original)[ring_outside(patch)].std()
        have = grain(result)[patch].std()
        noise = cv2.GaussianBlur(rng.standard_normal((SIZE, SIZE)).astype(np.float32), (0, 0), 0.7)
        noise *= np.sqrt(max(want**2 - have**2, 0)) / max(float(noise.std()), 1e-6)
        result += (noise * cv2.GaussianBlur(patch.astype(np.float32), (0, 0), 8))[..., None]
    return np.clip(result, 0, 255).astype(np.uint8)


def lab_lightness(pixels: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(pixels, cv2.COLOR_RGB2LAB)[..., 0].astype(np.float32) * 100 / 255


def edge_strength(values: np.ndarray) -> np.ndarray:
    gx = cv2.Sobel(values, cv2.CV_32F, 1, 0)
    gy = cv2.Sobel(values, cv2.CV_32F, 0, 1)
    return np.sqrt(gx**2 + gy**2)


def patch_checks(
    original: np.ndarray, generated: np.ndarray, cleaned: np.ndarray, patch: np.ndarray
) -> dict[str, float]:
    """echo: the generated patch still follows the original's edges, i.e. the
    item was only partly removed. texture: the patch's grain against the
    original's around it. texture_shape: the patch's grain traces the removed
    item, the 'shadow of the design'."""
    lo, lg, lc = lab_lightness(original), lab_lightness(generated), lab_lightness(cleaned)
    core = cv2.erode(patch.astype(np.uint8), np.ones((CLEAN_RING, CLEAN_RING), np.uint8)) > 0
    removed = np.abs(lo - lg) > CLEAN_CHANGE / 4
    around = patch | ring_outside(patch)
    texture_map = cv2.GaussianBlur(np.abs(grain(lc)), (0, 0), 6)
    removed_shape = cv2.GaussianBlur((removed & patch).astype(np.float32), (0, 0), 3)
    return {
        "echo": float(np.corrcoef(edge_strength(lo)[core], edge_strength(lg)[core])[0, 1]),
        "texture": float(grain(lc)[core].std() / grain(lc)[ring_outside(patch)].std()),
        "texture_shape": float(np.corrcoef(texture_map[around], removed_shape[around])[0, 1]),
    }


def patch_problems(index: int, checks: dict[str, float]) -> list[str]:
    low, high = TEXTURE_RATIO_RANGE
    problems = []
    if checks["echo"] > MAX_ECHO_R:
        problems.append(
            f"patch {index}: the generated image still follows the removed item's edges "
            f"(echo {checks['echo']:.2f}, max {MAX_ECHO_R}); regenerate with a note"
        )
    if abs(checks["texture_shape"]) > MAX_TEXTURE_SHAPE_R:
        problems.append(
            f"patch {index}: the patch's grain traces the removed item's shape "
            f"(r {checks['texture_shape']:+.2f}, max {MAX_TEXTURE_SHAPE_R})"
        )
    if not low <= checks["texture"] <= high:
        problems.append(
            f"patch {index}: grain {checks['texture']:.2f}x the surrounding original's "
            f"(allowed {low}-{high})"
        )
    return problems


def boosted(pixels: np.ndarray) -> np.ndarray:
    """Contrast x4 about the mean, so faint remnants and seams show."""
    values = pixels.astype(np.float32)
    mean = values.mean(axis=(0, 1))
    return np.clip((values - mean) * 4 + mean, 0, 255).astype(np.uint8)


def patch_review(
    out_dir: Path, index: int, original: np.ndarray, cleaned: np.ndarray, patch: np.ndarray
) -> Path:
    """The patch and its surroundings: original, cleaned, cleaned at contrast x4."""
    ys, xs = np.nonzero(patch)
    margin = 96
    top, bottom = max(0, ys.min() - margin), min(SIZE, ys.max() + margin)
    left, right = max(0, xs.min() - margin), min(SIZE, xs.max() + margin)
    crops = [
        original[top:bottom, left:right],
        cleaned[top:bottom, left:right],
        boosted(cleaned[top:bottom, left:right]),
    ]
    sheet = np.full((bottom - top, 3 * (right - left) + 16, 3), 255, np.uint8)
    for column, crop in enumerate(crops):
        x = column * (right - left + 8)
        sheet[:, x : x + right - left] = crop
    path = out_dir / f"clean-patch-{index}.jpg"
    Image.fromarray(sheet).save(path, quality=92)
    return path


def clean(args: argparse.Namespace) -> None:
    """Composite the generator's clean-up onto the original, check it, and
    write the cleaned 2048 source plus review images to --out-dir."""
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    original = load_square(Path(args.original))
    generated_path = Path(args.generated)
    generated = load_square(upscaled(out_dir, generated_path) if args.upscale else generated_path)
    patches = edited_patches(original, generated)
    if not patches:
        raise SystemExit("The generated image changed nothing large enough to be the edit.")
    cleaned = match_grain(clone_patches(original, generated, patches), original, patches)
    Image.fromarray(cleaned).save(out_dir / "cleaned.png")
    problems = []
    for index, patch in enumerate(patches):
        checks = patch_checks(original, generated, cleaned, patch)
        ys, xs = np.nonzero(patch)
        say(
            f"patch {index} x{xs.min()}-{xs.max()} y{ys.min()}-{ys.max()}: echo "
            f"{checks['echo']:.2f}  grain {checks['texture']:.2f}x  "
            f"grain-vs-shape {checks['texture_shape']:+.2f}  "
            f"review {patch_review(out_dir, index, original, cleaned, patch)}"
        )
        problems += patch_problems(index, checks)
    say(f"Cleaned source: {out_dir / 'cleaned.png'}")
    finish(problems)


# --- pilot ---------------------------------------------------------------


def run_meta(run_dir: Path) -> dict:
    return json.loads((run_dir / "run.json").read_text(encoding="utf-8"))


def outline_colour(run_dir: Path, pilots: list[str]) -> str:
    """The pilot furthest from the source: the dark one on a light shirt, and the
    reverse. A pilot close to the source changes the shirt too faintly to outline it."""
    source = load_rgb(run_dir / "source.png", ANALYSIS_SIZE)

    def distance(colour: str) -> float:
        pixels = load_rgb(run_dir / "out" / f"{slugify(colour)}.png", ANALYSIS_SIZE)
        return float(np.abs(pixels - source).mean())

    return max(pilots, key=distance)


def garment_outline(run_dir: Path, colour: str, size: int) -> np.ndarray:
    """The shirt as `colour` recoloured it: the changed pixels, closed, keeping
    only shirt-sized regions so stray changes (a light, jeans texture) drop out."""
    source = load_rgb(run_dir / "source.png", size)
    pixels = load_rgb(run_dir / "out" / f"{slugify(colour)}.png", size)
    changed = (np.abs(pixels - source).max(axis=2) > CHANGE_THRESHOLD).astype(np.uint8)
    closed = cv2.morphologyEx(changed, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    count, labels, stats, _ = cv2.connectedComponentsWithStats(closed)
    if count < 2:  # noqa: PLR2004 -- label 0 is the background; nothing changed
        return np.zeros_like(closed, bool)
    areas = stats[1:, cv2.CC_STAT_AREA]
    keep = 1 + np.flatnonzero(areas >= areas.max() * MIN_REGION_SHARE)
    return np.isin(labels, keep)


def load_reference(run_dir: Path) -> np.ndarray | None:
    path = run_dir / REFERENCE_MASK
    if not path.is_file():
        return None
    with Image.open(path) as image:
        return np.asarray(image.convert("L")) > 0


def outline_overlay(run_dir: Path, garment: np.ndarray) -> Path:
    """The source with the pilot's shirt outline drawn on it in green."""
    with Image.open(run_dir / "source.png") as image:
        canvas = np.array(image.convert("RGB"))
    scale = SIZE / garment.shape[0]
    contours, _ = cv2.findContours(
        garment.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
    )
    scaled = [np.rint(c * scale).astype(np.int32) for c in contours]
    cv2.drawContours(canvas, scaled, -1, (0, 255, 0), 3)
    path = run_dir / "review" / "pilot" / "outline.jpg"
    Image.fromarray(canvas).save(path, quality=92)
    return path


def tile_boxes(garment: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Full-resolution tiles covering the shirt and a margin around it."""
    ys, xs = np.nonzero(garment)
    scale = SIZE / garment.shape[0]
    left = max(0, int(xs.min() * scale) - TILE_MARGIN)
    top = max(0, int(ys.min() * scale) - TILE_MARGIN)
    right = min(SIZE, int((xs.max() + 1) * scale) + TILE_MARGIN)
    bottom = min(SIZE, int((ys.max() + 1) * scale) + TILE_MARGIN)
    return [
        (x, y, min(x + TILE, SIZE), min(y + TILE, SIZE))
        for y in range(top, bottom, TILE)
        for x in range(left, right, TILE)
    ]


def tile_sheets(run_dir: Path, pilots: list[str], garment: np.ndarray) -> list[Path]:
    """One image per tile: the source beside each pilot, at 1:1."""
    names = ["Source", *pilots]
    paths = [run_dir / "source.png", *(run_dir / "out" / f"{slugify(c)}.png" for c in pilots)]
    full = []
    for path in paths:
        with Image.open(path) as image:
            full.append(image.convert("RGB").resize((SIZE, SIZE), Image.Resampling.LANCZOS))
    font = ImageFont.load_default(size=22)
    sheets = []
    for box in tile_boxes(garment):
        width, height = box[2] - box[0], box[3] - box[1]
        sheet = Image.new("RGB", ((width + 8) * len(full), height + 34), "white")
        draw = ImageDraw.Draw(sheet)
        for index, (name, image) in enumerate(zip(names, full, strict=True)):
            sheet.paste(image.crop(box), (index * (width + 8), 34))
            draw.text(
                (index * (width + 8) + 6, 6),
                f"{name}  x{box[0]} y{box[1]}",
                fill="black",
                font=font,
            )
        path = run_dir / "review" / "pilot" / f"tile-x{box[0]:04d}-y{box[1]:04d}.jpg"
        sheet.save(path, quality=92)
        sheets.append(path)
    return sheets


def pilot_review(run_dir: Path, pilots: list[str]) -> None:
    pilot_dir = run_dir / "review" / "pilot"
    if pilot_dir.exists():
        shutil.rmtree(pilot_dir)
    pilot_dir.mkdir(parents=True)
    garment = garment_outline(run_dir, outline_colour(run_dir, pilots), SIZE // 2)
    say(f"Outline: {outline_overlay(run_dir, garment)}")
    say("Tiles (source | " + " | ".join(pilots) + "):")
    say("\n".join(str(p) for p in tile_sheets(run_dir, pilots, garment)))


def pilot_notes(run_dir: Path, pilots: list[str]) -> list[str]:
    """Every distinct `## Pilot review` section in the pilot briefs."""
    notes: list[str] = []
    for colour in pilots:
        text = brief_path(run_dir, colour).read_text(encoding="utf-8")
        for section in text.split(PILOT_NOTES_HEADING)[1:]:
            note = PILOT_NOTES_HEADING + section.split("\n## ")[0].rstrip()
            if note not in notes:
                notes.append(note)
    return notes


def approve_pilot(run_dir: Path, pilots: list[str]) -> None:
    """Freeze the reviewed outline and carry the pilot's guidance into every brief."""
    reference = garment_outline(run_dir, outline_colour(run_dir, pilots), ANALYSIS_SIZE)
    Image.fromarray((reference * 255).astype(np.uint8)).save(run_dir / REFERENCE_MASK)
    notes = pilot_notes(run_dir, pilots)
    others = [c for c in COLOURS if c not in pilots and brief_path(run_dir, c).is_file()]
    for colour in others:
        path = brief_path(run_dir, colour)
        text = path.read_text(encoding="utf-8")
        missing = [note for note in notes if note not in text]
        if missing:
            path.write_text(text.rstrip() + "\n\n" + "\n\n".join(missing) + "\n", encoding="utf-8")
    say(f"Reference outline: {run_dir / REFERENCE_MASK}")
    say(f"{len(notes)} pilot note(s) carried into {len(others)} briefs:")
    say("\n".join(str(brief_path(run_dir, c)) for c in others))


def pilot(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir)
    pilots = run_meta(run_dir)["pilots"]
    missing = [c for c in pilots if not (run_dir / "out" / f"{slugify(c)}.png").is_file()]
    if missing:
        raise SystemExit(f"Pilot photos missing: {', '.join(missing)}")
    if args.approve:
        approve_pilot(run_dir, pilots)
    else:
        pilot_review(run_dir, pilots)


# --- shading ---------------------------------------------------------------


def log_luminance(pixels: np.ndarray) -> np.ndarray:
    """Shading multiplies the dye colour, so in log luminance a recolour only
    shifts it; normalising each image then compares the pattern alone."""
    values = pixels / 255
    linear = np.where(values <= SRGB_KNEE, values / 12.92, ((values + 0.055) / 1.055) ** 2.4)
    return np.log(linear @ np.array([0.2126, 0.7152, 0.0722], np.float32) + 0.002)


def fabric_blur(values: np.ndarray, fabric: np.ndarray, sigma: float) -> np.ndarray:
    """Blur within the fabric only, so hair and background never bleed into it."""
    weight = fabric.astype(np.float32)
    total = cv2.GaussianBlur(values * weight, (0, 0), sigma)
    return total / np.maximum(cv2.GaussianBlur(weight, (0, 0), sigma), 1e-3)


def shading_bands(pixels: np.ndarray, fabric: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Broad lighting and folds, each normalised over the fabric."""
    logs = log_luminance(pixels)
    light = fabric_blur(logs, fabric, LIGHT_SIGMA)
    folds = fabric_blur(logs, fabric, FOLD_SIGMA) - light

    def normalise(band: np.ndarray) -> np.ndarray:
        values = band[fabric]
        return (band - np.median(values)) / (values.std() + 1e-6)

    return normalise(light), normalise(folds)


def fabric_mask(
    run_dir: Path, reference: np.ndarray | None, source: np.ndarray
) -> np.ndarray | None:
    """Shirt fabric visible in the source: inside the approved outline, where the
    outline pilot changed the photo strongly (hair lying over the shirt it left alone)."""
    if reference is None:
        return None
    outline = outline_colour(run_dir, run_meta(run_dir)["pilots"])
    pilot_pixels = load_rgb(run_dir / "out" / f"{slugify(outline)}.png", ANALYSIS_SIZE)
    fabric = (np.abs(pilot_pixels - source).max(axis=2) > FABRIC_THRESHOLD) & reference
    return cv2.erode(fabric.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0


def score_shading(
    run_dir: Path, results: list[Result], source: np.ndarray, fabric: np.ndarray
) -> None:
    """Compare each colour's lighting and folds with the source or an approved pilot,
    whichever is nearest in brightness: dark dye shows folds with more contrast
    than a light one, so a dark colour is held to the dark pilot."""
    pilots = run_meta(run_dir)["pilots"]
    references = {"Source": source} | {r.colour: r.pixels for r in results if r.colour in pilots}
    level = {name: float(log_luminance(p)[fabric].mean()) for name, p in references.items()}
    bands = {name: shading_bands(p, fabric) for name, p in references.items()}
    for result in results:
        own = float(log_luminance(result.pixels)[fabric].mean())
        others = [name for name in references if name != result.colour]
        ref = min(others, key=lambda name: abs(level[name] - own))
        light, folds = shading_bands(result.pixels, fabric)
        result.shading_ref = ref
        result.light_r = float(np.corrcoef(bands[ref][0][fabric], light[fabric])[0, 1])
        result.folds_r = float(np.corrcoef(bands[ref][1][fabric], folds[fabric])[0, 1])
        mismatch = (np.abs(bands[ref][0] - light) > SHADING_MISMATCH_Z) | (
            np.abs(bands[ref][1] - folds) > SHADING_MISMATCH_Z
        )
        result.shading_map = mismatch & fabric


def shading_failed(result: Result) -> bool:
    if result.light_r is None or result.folds_r is None:
        return False
    return result.light_r < MIN_LIGHT_R or result.folds_r < MIN_FOLDS_R


def save_shading_map(run_dir: Path, result: Result) -> Path:
    """The recolour with its mismatched shading painted cyan."""
    overlay = result.pixels.astype(np.uint8).copy()
    overlay[result.shading_map] = (0, 255, 255)
    path = run_dir / "review" / f"shading-{slugify(result.colour)}.png"
    Image.fromarray(overlay).save(path)
    return path


def save_drift_map(run_dir: Path, result: Result) -> Path:
    """The recolour with its drift pixels painted magenta, for the retry and review."""
    overlay = result.pixels.astype(np.uint8).copy()
    overlay[result.drift_map] = (255, 0, 255)
    path = run_dir / "review" / f"drift-{slugify(result.colour)}.png"
    Image.fromarray(overlay).save(path)
    return path


def measure(run_dir: Path) -> tuple[list[Result], list[str]]:
    """Load and score every recolour; problems include each drift over the limit
    and, once the pilot is approved, each shirt whose shading strays from the source."""
    source = load_rgb(run_dir / "source.png", ANALYSIS_SIZE)
    results, problems = load_results(run_dir, source)
    reference = load_reference(run_dir)
    score(results, reference)
    fabric = fabric_mask(run_dir, reference, source)
    if fabric is not None:
        score_shading(run_dir, results, source, fabric)
    (run_dir / "review").mkdir(exist_ok=True)
    for old in [
        *(run_dir / "review").glob("drift-*.png"),
        *(run_dir / "review").glob("shading-*.png"),
    ]:
        old.unlink()
    for result in results:
        problems += measured_problems(run_dir, result)
    return results, problems


def measured_problems(run_dir: Path, result: Result) -> list[str]:
    problems = []
    if result.drift > MAX_DRIFT_PCT:
        drift_path = save_drift_map(run_dir, result)
        problems.append(
            f"{result.colour}: drift {result.drift:.2f}% is over {MAX_DRIFT_PCT:g}%; "
            f"retry its brief (map: {drift_path})"
        )
    if shading_failed(result):
        shading_path = save_shading_map(run_dir, result)
        problems.append(
            f"{result.colour}: shading differs from {result.shading_ref} (lighting "
            f"{result.light_r:.2f}, min {MIN_LIGHT_R}; folds {result.folds_r:.2f}, "
            f"min {MIN_FOLDS_R}); retry its brief (map: {shading_path})"
        )
    return problems


def report_rows(run_dir: Path, results: list[Result]) -> None:
    report = [
        {
            "colour": r.colour,
            "target": COLOURS[r.colour],
            "measured": r.measured,
            "drift_pct": round(r.drift, 2),
            "shading_ref": r.shading_ref,
            "light_r": None if r.light_r is None else round(r.light_r, 3),
            "folds_r": None if r.folds_r is None else round(r.folds_r, 3),
        }
        for r in results
    ]
    (run_dir / "review" / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    for row in sorted(report, key=lambda item: -item["drift_pct"]):
        shading = (
            f"  lighting {row['light_r']} folds {row['folds_r']} vs {row['shading_ref']}"
            if row["shading_ref"]
            else ""
        )
        say(
            f"  {row['colour']:<12} target {row['target']}  "
            f"measured {row['measured']}  drift {row['drift_pct']}%{shading}"
        )


def finish(problems: list[str]) -> None:
    if problems:
        say("Problems:\n" + "\n".join(f"  - {p}" for p in problems))
        sys.exit(1)


def drift(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir)
    results, problems = measure(run_dir)
    report_rows(run_dir, results)
    finish(problems)


def assemble(args: argparse.Namespace) -> None:
    run_dir = Path(args.run_dir)
    scene = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))["scene"]
    results, problems = measure(run_dir)
    export_dir = export(run_dir, scene, results, upscale=args.upscale)
    sheets = review_sheets(run_dir, results, export_dir, scene)
    say(f"Export: {export_dir} ({len(results)} of {len(COLOURS)} colours)")
    say("Review sheets:\n" + "\n".join(str(p) for p in sheets))
    report_rows(run_dir, results)
    finish(problems)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)

    prep = commands.add_parser("prepare", help="check the source and write the Codex briefs")
    prep.add_argument("source", help="the 2048x2048 source photo")
    prep.add_argument("--scene", required=True, help="scene name used in export filenames")
    prep.add_argument("--run-dir", required=True, help="new directory for this run")
    prep.add_argument(
        "--source-colour", help="palette colour the source shirt already is; reused as-is"
    )
    prep.set_defaults(func=prepare)

    asm = commands.add_parser("assemble", help="build the export and review sheets from out/")
    asm.add_argument("run_dir")
    asm.add_argument(
        "--no-upscale",
        dest="upscale",
        action="store_false",
        help="resize with LANCZOS only, skipping the Upscayl Standard 4x upscale",
    )
    asm.set_defaults(func=assemble)

    dft = commands.add_parser("drift", help="measure drift only: no upscale, export or sheets")
    dft.add_argument("run_dir")
    dft.set_defaults(func=drift)

    cln = commands.add_parser(
        "clean", help="composite a generated clean-up onto the original and check it"
    )
    cln.add_argument("original", help="the photo as given, square")
    cln.add_argument("generated", help="the generator's edit of it, square")
    cln.add_argument("--out-dir", required=True, help="where cleaned.png and its review go")
    cln.add_argument(
        "--no-upscale",
        dest="upscale",
        action="store_false",
        help="skip the Upscayl Standard 4x upscale of the generated image",
    )
    cln.set_defaults(func=clean)

    plt = commands.add_parser(
        "pilot", help="build the pilot's review images, or --approve its outline and notes"
    )
    plt.add_argument("run_dir")
    plt.add_argument(
        "--approve",
        action="store_true",
        help="freeze the pilot's outline as the reference and copy its notes into every brief",
    )
    plt.set_defaults(func=pilot)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

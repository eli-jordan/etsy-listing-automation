"""Print files for design ideas, from Nano Banana 2.1 2K through Kie.ai.

    uv run python generate_designs.py generate NICHE_DIR [SLUG ...]
    uv run python generate_designs.py sheet NICHE_DIR
    uv run python generate_designs.py check NICHE_DIR|IDEA_DIR
    uv run python generate_designs.py archive IDEA_DIR
    uv run python generate_designs.py revise IDEA_DIR CHANGE_FILE
    uv run python generate_designs.py upscale-source IDEA_DIR [IDEA_DIR ...]
    uv run python generate_designs.py upscale-apply IDEA_DIR UPSCALED_IMAGE

`generate` works from NICHE_DIR/ideas/SLUG/prompt.md and the one style reference in
that idea's refs/ folder. With no slugs it fills in every idea with no print file. Naming
slugs regenerates them, keeping the previous generator output in raw/ as a .keep file.

The generator can't make transparency, so each prompt asks for a flat green or magenta
key background. `generate` saves that image to raw/SLUG.png, removes the background and
writes out/SLUG.png: a hard-edged transparent 4500x5400 PNG with the artwork centred
near the top.

`sheet` tiles every print file on its shirt colour, with its reference beside it, into
NICHE_DIR/designs-overview.jpg. `check` prints each print file's size, edges, open space
and generator resolution, and names anything that isn't print-ready.

`archive` copies out/SLUG.png to rejected/SLUG-vN.png, the next free N, unless the latest
archived version is already the same file. `revise` archives, then sends the current
print, flattened on its key colour, to Kie.ai as an edit with CHANGE_FILE's text as the
change to make, and cuts the result into out/SLUG.png.

`upscale-source` writes upscale/SLUG-source.png: the print cropped to its artwork,
flattened on its key colour and cut down to 1600 px on its long side, for Kittl's
upscaler. `upscale-apply` resizes the upscaled image back into the artwork's box, keeps
the original transparency and the original colours in a 6 px band along its edge, moves
the old print to out-pre-upscale/ and writes the new one to out/.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

sys.path.insert(0, str(Path(__file__).parents[1] / "create-mockup-template-cc1717"))
import kie

ASPECT_RATIO = "4:5"  # the closest the generator offers to the 5:6 print area
CANVAS = (4500, 5400)
MAX_ART = (4300, 5000)
TOP_MARGIN = 150
GREEN = (0, 255, 0)
MAGENTA = (255, 0, 255)
KEY_TOLERANCE = 110  # how far a background corner may sit from the pure key colour
ART_DISTANCE = 120  # pixels this far from the key colour are artwork
SPECK_PIXELS = 12
EDGE_BLUR = 1.2
EDGE_THRESHOLD = 150
ERODE_ITERATIONS = 2  # pulls the edge in past any key-coloured fringe
EDIT_SOURCE = (1856, 2304)  # the generator's 2K 4:5 size
UPSCALE_SOURCE = 1600  # long side sent to Kittl, which returns about 4096
EDGE_BAND = 13  # MinFilter size: keeps the original colours 6 px in from the edge
ASPECT_SLACK = 0.03
FULL_2K = 1800  # a raw narrower than this came back at 1K
OPEN_TARGET = 0.4  # share of the artwork's box left bare
SEMI_LIMIT = 0.005
OPAQUE = 255
CELL = (420, 504)
REFERENCE_WIDTH = 150
CAPTION = 18
PER_ROW = 4
SHIRT_HEX = re.compile(r"printed on an? [^(]*\((#[0-9a-f]{6})\)", re.IGNORECASE)
KEY_HEX = re.compile(r"background \((#[0-9a-f]{6})\)", re.IGNORECASE)
NEUTRAL_SHIRT = "#b4b4b4"
EDIT_PROMPT = """Edit the attached t-shirt design. Change only this:

{change}

Keep everything else exactly as it is: the composition, style, colours, line weights and \
every word. The background stays a perfectly flat solid {hex} filling the whole canvas, and \
{hex} appears nowhere in the artwork. Flat screen-print colour with crisp edges: no glows, \
soft shadows, sheen or semi-transparent areas."""


# ---------------------------------------------------------------- cutting out


def key_colour(pixels: np.ndarray) -> tuple[int, int, int]:
    corners = pixels[[8, 8, -9, -9], [8, -9, 8, -9]].astype(float).mean(axis=0)
    for colour in (GREEN, MAGENTA):
        if np.linalg.norm(corners - colour) < KEY_TOLERANCE:
            return colour
    raise ValueError(f"background is {corners.round().tolist()}, neither green nor magenta")


def despill(pixels: np.ndarray, key: tuple[int, int, int]) -> np.ndarray:
    """Remove the tint the key colour leaves on the artwork."""
    wide = pixels.astype(np.int32)
    red, green, blue = wide[..., 0], wide[..., 1], wide[..., 2]
    if key == GREEN:
        green = np.minimum(green, np.maximum(red, blue))
    else:
        excess = np.maximum(np.minimum(red, blue) - green, 0)
        red, blue = red - excess, blue - excess
    return np.dstack([red, green, blue]).astype(np.uint8)


def art_mask(pixels: np.ndarray, key: tuple[int, int, int]) -> np.ndarray:
    distance = np.linalg.norm(pixels.astype(np.int32) - np.array(key), axis=2)
    mask = (distance > ART_DISTANCE).astype(np.uint8) * 255
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    for label in range(1, count):
        if stats[label, cv2.CC_STAT_AREA] < SPECK_PIXELS:
            mask[labels == label] = 0
    return mask


def cut_out(raw: Path, output: Path) -> None:
    with Image.open(raw) as image:
        pixels = np.asarray(image.convert("RGB"))
    key = key_colour(pixels)
    mask = art_mask(pixels, key)
    ys, xs = np.where(mask)
    if not xs.size:
        raise ValueError("no artwork on the background")
    box = (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)
    art = despill(pixels, key)[box[1] : box[3], box[0] : box[2]]
    edge = mask[box[1] : box[3], box[0] : box[2]]
    scale = min(MAX_ART[0] / art.shape[1], MAX_ART[1] / art.shape[0])
    size = (round(art.shape[1] * scale), round(art.shape[0] * scale))
    big = np.asarray(Image.fromarray(art).resize(size, Image.Resampling.LANCZOS))
    soft = cv2.GaussianBlur(
        cv2.resize(edge, size, interpolation=cv2.INTER_CUBIC), (0, 0), EDGE_BLUR
    )
    alpha = cv2.erode(
        (soft > EDGE_THRESHOLD).astype(np.uint8) * 255,
        np.ones((3, 3), np.uint8),
        iterations=ERODE_ITERATIONS,
    )
    canvas = np.zeros((CANVAS[1], CANVAS[0], 4), np.uint8)
    left = (CANVAS[0] - size[0]) // 2
    area = canvas[TOP_MARGIN : TOP_MARGIN + size[1], left : left + size[0]]
    area[..., :3] = big
    area[..., 3] = alpha
    canvas[canvas[..., 3] == 0] = 0
    output.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(canvas).save(output, "PNG", dpi=(300, 300))


# ---------------------------------------------------------------- idea folders


def idea_dirs(niche: Path) -> dict[str, Path]:
    return {p.parent.name: p.parent for p in sorted((niche / "ideas").glob("*/prompt.md"))}


def raw_path(idea: Path) -> Path:
    return idea / "raw" / f"{idea.name}.png"


def print_path(idea: Path) -> Path:
    """out/SLUG.png, or the only PNG in out/ when an older brief named it differently."""
    expected = idea / "out" / f"{idea.name}.png"
    found = sorted((idea / "out").glob("*.png"))
    return found[0] if not expected.exists() and len(found) == 1 else expected


def reference(idea: Path) -> Path | None:
    """The idea's style reference, when its refs/ folder holds exactly one."""
    found = sorted((idea / "refs").glob("ref-*"))
    return found[0] if len(found) == 1 else None


def idea_key(idea: Path) -> tuple[int, int, int]:
    """The key colour the idea's prompt asked for, else the one its raw image used."""
    prompt = idea / "prompt.md"
    found = KEY_HEX.search(prompt.read_text(encoding="utf-8")) if prompt.exists() else None
    if found:
        value = found.group(1)
        return int(value[1:3], 16), int(value[3:5], 16), int(value[5:7], 16)
    if raw_path(idea).exists():
        with Image.open(raw_path(idea)) as image:
            return key_colour(np.asarray(image.convert("RGB")))
    return GREEN


def flattened(art: Image.Image, key: tuple[int, int, int]) -> Image.Image:
    backing = Image.new("RGBA", art.size, (*key, 255))
    backing.alpha_composite(art.convert("RGBA"))
    return backing.convert("RGB")


# ---------------------------------------------------------------- generate


def make_one(idea: Path, key: str, *, regenerate: bool) -> str | None:
    try:
        if regenerate or not raw_path(idea).exists():
            source = kie.upload(reference(idea), key)
            kie.generate(source, idea / "prompt.md", raw_path(idea), key, ASPECT_RATIO)
        cut_out(raw_path(idea), print_path(idea))
    except (kie.KieError, OSError, ValueError) as error:
        return f"{idea.name}: {error}"
    sys.stdout.write(f"{print_path(idea)}\n")
    return None


def chosen_ideas(ideas: dict[str, Path], slugs: list[str]) -> list[str]:
    unknown = [slug for slug in slugs if slug not in ideas]
    if unknown:
        sys.exit(f"no prompt.md for: {', '.join(unknown)}")
    return slugs or [slug for slug, idea in ideas.items() if not print_path(idea).exists()]


def require_references(ideas: dict[str, Path], slugs: list[str]) -> None:
    without_one = [slug for slug in slugs if reference(ideas[slug]) is None]
    if without_one:
        sys.exit(f"needs exactly one refs/ref-* image: {', '.join(without_one)}")


def paid_for(key: str, slugs: list[str]) -> None:
    try:
        kie.require_credits(key, slugs)
    except kie.KieError as error:
        sys.exit(str(error))


def generate(niche: Path, slugs: list[str]) -> None:
    ideas = idea_dirs(niche)
    chosen = chosen_ideas(ideas, slugs)
    if not chosen:
        sys.stdout.write("Every idea has a print file. Name slugs to regenerate.\n")
        return
    key = kie.api_key()
    paid = [s for s in chosen if slugs or not raw_path(ideas[s]).exists()]
    require_references(ideas, paid)
    paid_for(key, paid)
    with ThreadPoolExecutor(kie.CONCURRENCY) as pool:
        results = pool.map(lambda s: make_one(ideas[s], key, regenerate=bool(slugs)), chosen)
        failures = [failure for failure in results if failure]
    if failures:
        sys.exit(kie.failure_message(failures, key))


# ---------------------------------------------------------------- revise


def archive(idea: Path) -> Path:
    current = print_path(idea)
    if not current.exists():
        sys.exit(f"no print file at {current}")
    version = re.compile(rf"{re.escape(current.stem)}-v(\d+)")
    found = [(version.fullmatch(p.stem), p) for p in (idea / "rejected").glob("*.png")]
    kept = sorted((int(m.group(1)), p) for m, p in found if m)
    if kept and kept[-1][1].read_bytes() == current.read_bytes():
        return kept[-1][1]
    number = kept[-1][0] + 1 if kept else 1
    target = idea / "rejected" / f"{current.stem}-v{number}.png"
    target.parent.mkdir(exist_ok=True)
    shutil.copy2(current, target)
    return target


def edit_source(idea: Path, key: tuple[int, int, int]) -> Path:
    with Image.open(print_path(idea)) as image:
        flat = flattened(image, key)
    flat.thumbnail(EDIT_SOURCE, Image.Resampling.LANCZOS)
    source = idea / "raw" / f"{idea.name}-edit-source.png"
    source.parent.mkdir(exist_ok=True)
    flat.save(source)
    return source


def revise(idea: Path, change: Path) -> None:
    text = change.read_text(encoding="utf-8").strip()
    if not text:
        sys.exit(f"{change} is empty")
    sys.stdout.write(f"archived {archive(idea)}\n")
    colour = idea_key(idea)
    brief = idea / "raw" / f"{idea.name}-edit.md"
    source = edit_source(idea, colour)
    hex_code = "#{:02X}{:02X}{:02X}".format(*colour)
    brief.write_bytes(EDIT_PROMPT.format(change=text, hex=hex_code).encode("utf-8"))
    key = kie.api_key()
    paid_for(key, [idea.name])
    try:
        kie.generate(kie.upload(source, key), brief, raw_path(idea), key, ASPECT_RATIO)
        cut_out(raw_path(idea), print_path(idea))
    except (kie.KieError, OSError, ValueError) as error:
        sys.exit(kie.failure_message([f"{idea.name}: {error}"], key))
    sys.stdout.write(f"{print_path(idea)}\n")


# ---------------------------------------------------------------- upscale


def upscale_source(idea: Path) -> Path:
    with Image.open(print_path(idea)) as image:
        art = image.convert("RGBA")
    box = art.getchannel("A").getbbox()
    if box is None:
        sys.exit(f"{print_path(idea)} is empty")
    flat = flattened(art.crop(box), idea_key(idea))
    flat.thumbnail((UPSCALE_SOURCE, UPSCALE_SOURCE), Image.Resampling.LANCZOS)
    out = idea / "upscale" / f"{idea.name}-source.png"
    out.parent.mkdir(exist_ok=True)
    flat.save(out)
    return out


def upscale_apply(idea: Path, upscaled: Path) -> None:
    current = print_path(idea)
    with Image.open(current) as image:
        art = image.convert("RGBA")
    alpha = art.getchannel("A")
    box = alpha.getbbox()
    if box is None:
        sys.exit(f"{current} is empty")
    size = (box[2] - box[0], box[3] - box[1])
    with Image.open(upscaled) as image:
        big = image.convert("RGB")
    if abs(big.width / big.height - size[0] / size[1]) > ASPECT_SLACK * size[0] / size[1]:
        sys.exit(f"{upscaled} is {big.size}, not the shape of the artwork's box {size}")
    big = big.resize(size, Image.Resampling.LANCZOS)
    crop_alpha = alpha.crop(box)
    pad = EDGE_BAND // 2 + 1  # the box's own border is an edge too
    padded = ImageOps.expand(crop_alpha, border=pad, fill=0)
    core = padded.filter(ImageFilter.MinFilter(EDGE_BAND)).crop(
        (pad, pad, pad + size[0], pad + size[1])
    )
    rgb = Image.composite(big, art.crop(box).convert("RGB"), core)
    patch = rgb.convert("RGBA")
    patch.putalpha(crop_alpha)
    result = Image.new("RGBA", CANVAS, (0, 0, 0, 0))
    result.paste(patch, box[:2])
    keep = idea / "out-pre-upscale" / current.name
    keep.parent.mkdir(exist_ok=True)
    current.replace(keep)
    result.save(current, "PNG", dpi=(300, 300))
    sys.stdout.write(f"{current} (old print in {keep})\n")


# ---------------------------------------------------------------- check


def print_problems(image: Image.Image) -> tuple[list[str], float]:
    """What stops this image printing as it is, and the share of its box left bare."""
    if image.size != CANVAS or image.mode != "RGBA":
        return [f"{image.width}x{image.height} {image.mode}, not {CANVAS[0]}x{CANVAS[1]} RGBA"], 0
    alpha = image.getchannel("A")
    problems = []
    right, bottom = image.width - 1, image.height - 1
    corners = [alpha.getpixel(xy) for xy in ((0, 0), (right, 0), (0, bottom), (right, bottom))]
    if any(corners):
        problems.append("opaque corner")
    small = np.asarray(alpha.resize((900, 1080)))
    semi = float(((small > 0) & (small < OPAQUE)).mean())
    if semi > SEMI_LIMIT:
        problems.append(f"{semi:.1%} semi-transparent")
    box = alpha.getbbox()
    if box is None:
        return [*problems, "no artwork"], 0
    inside = np.asarray(alpha.crop(box))
    return problems, float((inside == 0).mean())


def raw_note(idea: Path) -> str:
    if not raw_path(idea).exists():
        return "no raw"
    with Image.open(raw_path(idea)) as image:
        width, height = image.size
    note = f"raw {width}x{height}"
    return note + " (1K: regenerate or upscale)" if width < FULL_2K else note


def check(folder: Path) -> None:
    """Check one idea folder, or every idea in a niche run."""
    found = [folder] if (folder / "prompt.md").exists() else idea_dirs(folder).values()
    ideas = [idea for idea in found if print_path(idea).exists()]
    if not ideas:
        sys.exit("no print files to check")
    for idea in ideas:
        sys.stdout.write(f"{idea.name}: {check_line(idea)}\n")


def check_line(idea: Path) -> str:
    with Image.open(print_path(idea)) as image:
        problems, bare = print_problems(image)
    notes = [f"open {bare:.0%}", raw_note(idea)]
    if (idea / "out-pre-upscale").is_dir():
        notes.append("upscaled")
    if bare < OPEN_TARGET:
        notes.append("crowded")
    verdict = "; ".join(problems) if problems else "ok"
    return f"{verdict}  ({', '.join(notes)})"


# ---------------------------------------------------------------- sheet


def shirt_colour(idea: Path) -> str:
    found = SHIRT_HEX.search((idea / "prompt.md").read_text(encoding="utf-8"))
    return found.group(1) if found else NEUTRAL_SHIRT


def design_cell(idea: Path) -> Image.Image:
    cell = Image.new("RGB", CELL, shirt_colour(idea))
    with Image.open(print_path(idea)) as image:
        art = image.convert("RGBA")
    art.thumbnail(CELL, Image.Resampling.LANCZOS)
    cell.paste(art, ((CELL[0] - art.width) // 2, 0), art)
    return cell


def paste_reference(tiled: Image.Image, idea: Path, origin: tuple[int, int]) -> None:
    source = reference(idea)
    if source is None:
        return
    with Image.open(source) as image:
        thumb = image.convert("RGB")
    thumb.thumbnail((REFERENCE_WIDTH - 6, CELL[1]), Image.Resampling.LANCZOS)
    tiled.paste(thumb, origin)


def sheet(niche: Path) -> None:
    ideas = [idea for idea in idea_dirs(niche).values() if print_path(idea).exists()]
    if not ideas:
        sys.exit("no print files to tile")
    rows = (len(ideas) + PER_ROW - 1) // PER_ROW
    width = CELL[0] + REFERENCE_WIDTH
    tiled = Image.new("RGB", (PER_ROW * width, rows * (CELL[1] + CAPTION)), "white")
    draw = ImageDraw.Draw(tiled)
    for index, idea in enumerate(ideas):
        x, y = index % PER_ROW * width, index // PER_ROW * (CELL[1] + CAPTION)
        draw.text((x + 4, y + 3), idea.name, fill="black")
        tiled.paste(design_cell(idea), (x, y + CAPTION))
        paste_reference(tiled, idea, (x + CELL[0] + 3, y + CAPTION))
    output = niche / "designs-overview.jpg"
    tiled.save(output, quality=88)
    sys.stdout.write(f"{output}\n")


# ---------------------------------------------------------------- command line


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    commands = top.add_subparsers(dest="command", required=True)
    make = commands.add_parser("generate")
    make.add_argument("niche", type=Path)
    make.add_argument("slugs", nargs="*", help="ideas to regenerate; default: those with no file")
    commands.add_parser("sheet").add_argument("niche", type=Path)
    commands.add_parser("check").add_argument("niche", type=Path, help="a niche run or idea")
    commands.add_parser("archive").add_argument("idea", type=Path)
    change = commands.add_parser("revise")
    change.add_argument("idea", type=Path)
    change.add_argument("change", type=Path, help="a text file saying what to change")
    commands.add_parser("upscale-source").add_argument("ideas", type=Path, nargs="+")
    apply = commands.add_parser("upscale-apply")
    apply.add_argument("idea", type=Path)
    apply.add_argument("upscaled", type=Path)
    return top


def main() -> None:
    args = parser().parse_args()
    commands: dict[str, Callable[[], object]] = {
        "generate": lambda: generate(args.niche, args.slugs),
        "sheet": lambda: sheet(args.niche),
        "check": lambda: check(args.niche),
        "archive": lambda: sys.stdout.write(f"{archive(args.idea)}\n"),
        "revise": lambda: revise(args.idea, args.change),
        "upscale-source": lambda: [
            sys.stdout.write(f"{upscale_source(idea)}\n") for idea in args.ideas
        ],
        "upscale-apply": lambda: upscale_apply(args.idea, args.upscaled),
    }
    commands[args.command]()


if __name__ == "__main__":
    main()

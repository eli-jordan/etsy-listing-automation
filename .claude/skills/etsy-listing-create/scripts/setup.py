"""Listing setup through the app's HTTP API: create, read briefs, build galleries, move prints.

Every write goes through the app, and every write prints the field errors and
block issues that came back, so a refused or blocked save is never missed.
Run `setup.py COMMAND --help` for each command's arguments.
"""

import argparse
import io
import json
import math
import re
import sys
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from PIL import Image

MAX_IMAGES = 20
FIXED_SLOTS = 3  # hero, size guide, info card. The video is counted apart.
POLL_SECONDS = 10
WAIT_LIMIT_SECONDS = 1800
TERMINAL_AI = {"done", "failed", "cancelled", "cancelled_by_deploy"}
UNIT = np.array([[0, 0], [1, 0], [1, 1], [0, 1]], float)
VARIANT_SUFFIX = re.compile(r"-[a-z]$")
SPEC_FIELDS = 2
POINTS = 4
COPY_FIELDS = {"etsy.title", "etsy.tags", "etsy.description.lead"}
PREVIEW_EDGE = 900
BACKDROPS = ((128, 128, 128), (28, 28, 30), (236, 236, 232))


def say(*parts: object) -> None:
    sys.stdout.write(" ".join(str(p) for p in parts) + "\n")


def call(
    url: str,
    method: str = "GET",
    body: Any = None,
    raw: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> Any:
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    sent = {"Content-Type": "application/json"} if body is not None else {}
    request = urllib.request.Request(url, data=data, method=method, headers=sent | (headers or {}))
    with urllib.request.urlopen(request, timeout=600) as response:
        text = response.read()
    return json.loads(text) if text else None


def listing_url(base: str, name: str) -> str:
    return f"{base}/api/listings/{urllib.parse.quote(name)}"


def copy_pending(message: str) -> bool:
    """A block that only says the title, tags or lead are still to be written."""
    return message.split(" ", 1)[0].rstrip(",:") in COPY_FIELDS


def sorted_issues(detail: dict[str, Any]) -> dict[str, list[str]]:
    """Field errors, real blocks, the copy still to write, and warnings."""
    issues = detail.get("issues", [])
    blocks = [i["message"] for i in issues if i["severity"] == "block"]
    return {
        "FIELD ERRORS": [f"{k}: {v}" for k, v in (detail.get("field_errors") or {}).items()],
        "BLOCKS": [m for m in blocks if not copy_pending(m)],
        "copy still to write": [m.split(" ", 1)[0] for m in blocks if copy_pending(m)],
        "warnings": [i["message"] for i in issues if i["severity"] == "warn"],
    }


def report(detail: dict[str, Any]) -> bool:
    """Print what a save left wrong. True when nothing blocks but the copy still to write."""
    found = sorted_issues(detail)
    for label, items in found.items():
        if items:
            say(f"{label}:", json.dumps(items, ensure_ascii=False))
    return not found["FIELD ERRORS"] and not found["BLOCKS"]


def patch(base: str, name: str, body: dict[str, Any]) -> bool:
    ok = report(call(listing_url(base, name), "PATCH", body))
    say("saved" if ok else "NOT CLEAN: fix the items above")
    return ok


def cmd_health(args: argparse.Namespace) -> None:
    root = call(f"{args.url}/api/health")["workspace"]
    match = Path(root).resolve() == Path(args.root).resolve()
    say("workspace", root, "matches" if match else "DOES NOT MATCH --root")
    if not match:
        sys.exit(1)


def multipart(fields: dict[str, str], files: list[Path]) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    parts: list[bytes] = []
    for key, value in fields.items():
        parts.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n'
            f"{value}\r\n".encode()
        )
    for file in files:
        head = (
            f'--{boundary}\r\nContent-Disposition: form-data; name="files"; '
            f'filename="{file.name}"\r\nContent-Type: image/png\r\n\r\n'
        )
        parts.append(head.encode() + file.read_bytes() + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def listing_name(prefix: str, source: str, *, strip_variant: bool) -> str:
    stem = re.sub(r"[^a-z0-9]+", "-", Path(source).stem.lower()).strip("-")
    return prefix + (VARIANT_SUFFIX.sub("", stem) if strip_variant else stem)


def cmd_create(args: argparse.Namespace) -> None:
    files = [Path(f) for f in args.files]
    body, kind = multipart({"listing_template": args.template}, files)
    staged = call(f"{args.url}/api/staging", "POST", raw=body, headers={"Content-Type": kind})
    names = {
        r["id"]: listing_name(args.prefix, r["sources"][0], strip_variant=args.strip_variant)
        for r in staged["rows"]
    }
    staged = call(
        f"{args.url}/api/staging/{staged['id']}", "PATCH", {"label": args.label, "names": names}
    )
    for row in staged["rows"]:
        say(row["state"], row["name"], row.get("message") or "")
    if any(r["state"] != "ready" for r in staged["rows"]) or args.dry_run:
        say("staging", staged["id"], "left unconfirmed")
        return
    batch = call(f"{args.url}/api/staging/{staged['id']}/confirm", "POST")
    say("batch", batch["id"])
    for row in batch["rows"]:
        say(row["creation"], row["name"], row.get("error") or "")


def cmd_briefs(args: argparse.Namespace) -> None:
    started = time.time()
    while True:
        batch = call(f"{args.url}/api/batches/{args.batch}")
        pending = [r for r in batch["rows"] if r.get("ai") not in TERMINAL_AI]
        if not pending or time.time() - started > WAIT_LIMIT_SECONDS:
            break
        time.sleep(POLL_SECONDS)
    for row in batch["rows"]:
        brief = call(listing_url(args.url, row["name"])).get("brief") or ""
        say(f"## {row['name']} [{row.get('ai')}] {row.get('ai_error') or ''}")
        say(brief)


SHARED_FILES = {
    "video": lambda f: f.endswith(".mp4"),
    "size": lambda f: "size-guide" in f and not f.endswith(".mp4"),
    "info": lambda f: "info-card" in f,
}


def fixed_media(media: list[Any]) -> dict[str, str]:
    """The template's shared files, found by name, so any garment's set works."""
    files = [m for m in media if isinstance(m, str)]
    found = {key: [f for f in files if test(f)] for key, test in SHARED_FILES.items()}
    missing = [key for key, matches in found.items() if not matches]
    if missing:
        sys.exit(f"listing media lacks the shared {missing}; add them first")
    return {key: matches[0] for key, matches in found.items()}


def scene_entries(scenes: list[str], colours: list[str], hero: str) -> list[dict[str, str]]:
    """`template` or `template:colour`; a bare template takes the next colour in turn."""
    cycle = [c for c in colours if c != hero] + [hero]
    entries = []
    for index, scene in enumerate(scenes):
        template, _, colour = scene.partition(":")
        entries.append({"template": template, "colour": colour or cycle[index % len(cycle)]})
    return entries


def gallery(fixed: dict[str, str], args: argparse.Namespace) -> list[Any]:
    colours, hero = args.colours.split(","), args.hero
    if hero not in colours:
        sys.exit(f"hero {hero} is not one of the colours")
    tail = [c for c in colours if c != hero]
    scenes = scene_entries(args.scenes.split(","), colours, hero)
    room = MAX_IMAGES - FIXED_SLOTS - len(tail)
    if len(scenes) > room:
        sys.exit(f"{len(colours)} colours leave room for {room} scenes, not {len(scenes)}")
    unsold = {s["colour"] for s in scenes} - set(colours)
    if unsold:
        sys.exit(f"scene colours not sold: {sorted(unsold)}")
    return [
        {"template": args.variation, "colour": hero},
        fixed["video"],
        fixed["size"],
        *scenes,
        fixed["info"],
        *({"template": args.variation, "colour": c} for c in tail),
    ]


def cmd_gallery(args: argparse.Namespace) -> None:
    current = call(listing_url(args.url, args.name))
    media = gallery(fixed_media(current["media"]), args)
    colours = args.colours.split(",")
    used = {m["template"] for m in media if isinstance(m, dict)}
    positions = {t: p for t, p in (current.get("template_positions") or {}).items() if t in used}
    body: dict[str, Any] = {
        "colors": colours,
        "media": media,
        "etsy": {"variation_images": args.variation},
    }
    body["template_positions"] = positions or None
    say(f"{len(colours)} colours, {len(media) - 1} images and 1 video")
    patch(args.url, args.name, body)


def homography(points: Any) -> Any:
    rows, values = [], []
    for (x, y), (u, v) in zip(UNIT, points, strict=True):
        rows += [[x, y, 1, 0, 0, 0, -u * x, -u * y], [0, 0, 0, x, y, 1, -v * x, -v * y]]
        values += [u, v]
    return np.append(np.linalg.solve(np.array(rows), np.array(values)), 1).reshape(3, 3)


def moved_box(root: Path, template: str, numbers: list[float]) -> list[dict[str, float]]:
    """The template's box scaled, shifted and turned in its own flat frame, as the app requires."""
    scale, dy, dx, turn = [*numbers, 0.0, 0.0, 0.0][:4]
    path = root / "mockup-templates" / template / "template.yaml"
    box = yaml.safe_load(path.read_text(encoding="utf8"))["bounding_box"]
    corners = np.array([[p["x"], p["y"]] for p in box], float)
    angle = math.radians(turn)
    rotation = np.array([[math.cos(angle), -math.sin(angle)], [math.sin(angle), math.cos(angle)]])
    flat = (UNIT - 0.5) * scale @ rotation.T + 0.5 + [dx, dy]
    mapped = np.c_[flat, np.ones(POINTS)] @ homography(corners).T
    points = mapped[:, :2] / mapped[:, 2:]
    return [{"x": round(float(x), 6), "y": round(float(y), 6)} for x, y in points]


def cmd_position(args: argparse.Namespace) -> None:
    current = call(listing_url(args.url, args.name))
    positions = dict(current.get("template_positions") or {})
    for template in args.clear:
        positions.pop(template, None)
    for spec in args.moves:
        template, *numbers = spec.split(":")
        if len(numbers) < SPEC_FIELDS - 1:
            sys.exit(f"{spec}: give at least template:scale")
        box = moved_box(Path(args.root), template, [float(n) for n in numbers])
        positions[template] = {"bounding_box": box}
    patch(args.url, args.name, {"template_positions": positions or None})


def cmd_look(args: argparse.Namespace) -> None:
    """Print the brief and section, and draw each design file on grey, dark and light."""
    detail = call(listing_url(args.url, args.name))
    say("section:", (detail.get("etsy") or {}).get("section"))
    say("brief:", detail.get("brief") or "(empty)")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    listing = Path(args.root) / "listings" / args.name / "listing.yaml"
    document = yaml.safe_load(listing.read_text(encoding="utf8"))
    for key, ref in (document.get("design") or {}).items():
        art = Image.open(Path(args.root) / ref).convert("RGBA")
        art.thumbnail((PREVIEW_EDGE, PREVIEW_EDGE), Image.Resampling.LANCZOS)
        sheet = Image.new("RGB", (art.width * len(BACKDROPS), art.height))
        for index, colour in enumerate(BACKDROPS):
            sheet.paste(Image.new("RGB", art.size, colour), (index * art.width, 0))
            sheet.paste(art, (index * art.width, 0), art)
        path = out / f"design-{key}.jpg"
        sheet.save(path, quality=88)
        say("design", key, path)


def cmd_brief(args: argparse.Namespace) -> None:
    text = Path(args.file).read_text(encoding="utf8").strip() if args.file else args.text
    patch(args.url, args.name, {"brief": text})


def cmd_check(args: argparse.Namespace) -> None:
    for name in args.names:
        detail = call(listing_url(args.url, name))
        etsy = detail.get("etsy") or {}
        say(
            f"## {name}: {len(detail['colors'])} colours, {len(detail['media'])} media, "
            f"{len(etsy.get('tags') or [])} tags, title {len(etsy.get('title') or '')} chars"
        )
        say("clean" if report(detail) else "NOT CLEAN")


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description=__doc__)
    top.add_argument("--url", default="http://127.0.0.1:8000")
    commands = top.add_subparsers(dest="command", required=True)
    health = commands.add_parser("health", help="Confirm the app serves --root")
    health.add_argument("--root", required=True)
    create = commands.add_parser("create", help="Stage PNGs, name them and confirm the batch")
    create.add_argument("--template", required=True)
    create.add_argument("--prefix", default="")
    create.add_argument("--label", default="etsy-listing-create")
    create.add_argument("--strip-variant", action="store_true", help="drop a trailing -a, -b")
    create.add_argument("--dry-run", action="store_true")
    create.add_argument("files", nargs="+")
    briefs = commands.add_parser("briefs", help="Wait for the batch's briefs, then print them")
    briefs.add_argument("batch")
    gallery_cmd = commands.add_parser("gallery", help="Set colours and the gallery in one save")
    gallery_cmd.add_argument("name")
    gallery_cmd.add_argument("--colours", required=True, help="comma-separated")
    gallery_cmd.add_argument("--hero", required=True)
    gallery_cmd.add_argument("--variation", required=True)
    gallery_cmd.add_argument("--scenes", required=True, help="template or template:colour, ...")
    position = commands.add_parser("position", help="Move prints: template:scale[:dy[:dx[:deg]]]")
    position.add_argument("name")
    position.add_argument("--root", required=True)
    position.add_argument("--clear", nargs="*", default=[])
    position.add_argument("moves", nargs="*")
    look = commands.add_parser("look", help="Brief, section and the design on three backdrops")
    look.add_argument("name")
    look.add_argument("--root", required=True)
    look.add_argument("--out", required=True)
    brief = commands.add_parser("brief", help="Replace a listing's brief")
    brief.add_argument("name")
    brief.add_argument("text", nargs="?", default="")
    brief.add_argument("--file", help="read the brief from this file instead")
    check = commands.add_parser("check", help="Counts and issues for listings")
    check.add_argument("names", nargs="+")
    handlers = {
        "health": cmd_health,
        "create": cmd_create,
        "briefs": cmd_briefs,
        "gallery": cmd_gallery,
        "position": cmd_position,
        "check": cmd_check,
        "look": cmd_look,
        "brief": cmd_brief,
    }
    top.set_defaults(handlers=handlers)
    return top


def main() -> None:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    args = parser().parse_args()
    args.handlers[args.command](args)


if __name__ == "__main__":
    main()

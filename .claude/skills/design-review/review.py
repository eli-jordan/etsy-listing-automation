"""Build an interactive Publish / Iterate / Drop review page for a set of generated designs.

    uv run python review.py scan REVIEW_DIR IDEAS_DIR [IDEAS_DIR ...]
    uv run python review.py build REVIEW_DIR
    uv run python review.py results REVIEW_DIR ROWS_FILE
    uv run python review.py iterate REVIEW_DIR

scan     drafts REVIEW_DIR/review.json from idea folders (IDEAS_DIR/NN-slug/out/*.png,
         refs/, prompt.md). Each IDEAS_DIR becomes one group. Re-running keeps the records
         already in review.json and adds new ones.
build    checks review.json, writes the page and its images to REVIEW_DIR/site/, and
         writes the publish batches to REVIEW_DIR/publish-batches.json.
results  reads the rows an ArtifactData list of the `reviews` collection returned (pasted
         into ROWS_FILE), writes REVIEW_DIR/review-results.json and prints tags by verdict.
         A review-results.json from an earlier round is kept as review-results-roundN.json.
iterate  writes revision-N.md, a brief filled from revision-brief.md, into the folder of
         every design review-results.json tags Iterate, and prints their paths.
"""

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from PIL import Image

TEMPLATE = Path(__file__).with_name("review_template.html")
REVISION_BRIEF = Path(__file__).with_name("revision-brief.md")
REPO = Path(__file__).resolve().parents[3]
ETSY = "https://www.etsy.com/listing/"
DESIGN_MAX = (2250, 2700)  # half the 4500x5400 print: sharp at actual size, small to publish
DESIGN_THUMB = (900, 1080)
REF_MAX = (2000, 2000)
REF_THUMB = (720, 720)
BATCH_FILES = 240  # Artifact publish limits: 255 files and 64 MB per call
BATCH_BYTES = 60_000_000
FILE_BYTES = 16_000_000
SKIP_DIRS = {"rejected", "out-pre-upscale", "raw"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
# Display colours for shirt names a prompt gives without a hex. A hex in the prompt wins.
SHIRTS = {
    "black": "#1c1c1c",
    "white": "#f6f6f4",
    "ivory": "#f0ebdc",
    "pepper": "#52504c",
    "moss": "#707a5c",
    "chambray": "#bdd0d8",
    "natural": "#efe6d2",
    "navy": "#26304a",
    "grey": "#7d7c76",
    "gray": "#7d7c76",
    "red": "#b3262f",
    "blue jean": "#6d8299",
}
SHIRT_HEX = re.compile(r"printed on an? ([a-z ]+?) (?:t-)?shirt \((#[0-9a-f]{6})\)", re.IGNORECASE)
SHIRT_NAME = re.compile(r"printed on:?\**:? an? ([a-z ]+?) (?:t-)?shirt", re.IGNORECASE)
CONCEPT = re.compile(r"^\W*concept\W*\s*", re.IGNORECASE)
LISTING_ID = re.compile(r"(\d{7,})")
ID_SHAPE = re.compile(r"[a-z0-9-]{1,120}")
HEX = re.compile(r"#[0-9a-fA-F]{6}")
VERDICTS = ("publish", "iterate", "drop")
REQUIRED = ("title", "style", "idea", "shirtName")


def say(text: str) -> None:
    sys.stdout.write(text + "\n")


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def manifest_path(review: Path) -> Path:
    return review / "review.json"


def load(review: Path) -> dict:
    path = manifest_path(review)
    if not path.exists():
        return {"title": "", "intro": "", "groups": [], "designs": []}
    return json.loads(path.read_text(encoding="utf8"))


def write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((json.dumps(data, indent=1, ensure_ascii=False) + "\n").encode("utf8"))


# ---------- scan ----------


def print_file(idea: Path) -> Path | None:
    pngs = sorted((idea / "out").glob("*.png"))
    return pngs[0] if pngs else None


def text_line(line: str) -> str:
    """The quoted words of a prompt line that pins the design's exact text, else ''."""
    low = line.lower()
    if "exactly" in low and '"' in line and ("text" in low or "words" in low):
        quotes = [q.strip() for q in re.findall(r'"([^"]+)"', line)]
        return " / ".join(q for q in quotes if re.search(r"\w", q))
    return ""


def shirt_hint(text: str) -> tuple[str, str]:
    if m := SHIRT_HEX.search(text):
        return m.group(1).strip().title(), m.group(2).lower()
    if m := SHIRT_NAME.search(text):
        name = m.group(1).strip().lower()
        return name.title(), SHIRTS.get(name, "")
    return "", ""


def prompt_hints(idea: Path) -> dict:
    """Pull the text, shirt and concept out of prompt.md, whichever brief format wrote it."""
    path = idea / "prompt.md"
    text = path.read_text(encoding="utf8") if path.exists() else ""
    lines = text.splitlines()
    title = next((t for t in map(text_line, lines) if t), "")
    concept = next((CONCEPT.sub("", ln).strip() for ln in lines if CONCEPT.match(ln)), "")
    name, hexcode = shirt_hint(text)
    return {"title": title, "shirtName": name, "shirt": hexcode, "concept": concept}


def ref_record(path: Path) -> dict:
    lid = LISTING_ID.search(path.stem)
    return {
        "kind": "Style reference",
        "caption": f"Etsy listing {lid.group(1)}" if lid else path.stem,
        "link": ETSY + lid.group(1) if lid else None,
        "file": str(path),
    }


def ref_records(idea: Path) -> list[dict]:
    files = sorted(p for p in (idea / "refs").glob("*") if p.suffix.lower() in IMAGE_EXTS)
    return [ref_record(p) for p in files]


def design_record(idea: Path, png: Path, gkey: str, folder: str) -> dict:
    hints = prompt_hints(idea)
    num = re.match(r"(\d+)", idea.name)
    return {
        "id": slug(f"{gkey}-{idea.name}"),
        "group": gkey,
        "sub": "",
        "n": num.group(1) if num else "",
        "title": hints["title"],
        "style": "",
        "shirt": hints["shirt"],
        "shirtName": hints["shirtName"],
        "idea": "",
        "concept": hints["concept"],
        "file": str(png),
        "folder": folder,
        "refs": ref_records(idea),
    }


def idea_folders(ideas: Path) -> list[Path]:
    """Idea folders under IDEAS_DIR that hold a print file."""
    dirs = sorted(p for p in ideas.iterdir() if p.is_dir() and p.name not in SKIP_DIRS)
    return [p for p in dirs if print_file(p)]


def add_group(data: dict, ideas: Path) -> str:
    run = ideas.parent.name
    gkey = slug(f"{run}-{ideas.name}")[:60]
    if gkey not in {g["key"] for g in data["groups"]}:
        data["groups"].append({"key": gkey, "name": f"{run} / {ideas.name}", "blurb": ""})
    return gkey


def scan_dir(ideas: Path, data: dict) -> int:
    """Add one group for IDEAS_DIR and a record per idea folder holding a print file."""
    gkey = add_group(data, ideas)
    known = {d["id"] for d in data["designs"]}
    folder = f"{ideas.parent.name}/{ideas.name}"
    recs = [
        design_record(i, print_file(i), gkey, f"{folder}/{i.name}") for i in idea_folders(ideas)
    ]
    fresh = [r for r in recs if r["id"] not in known]
    data["designs"].extend(fresh)
    return len(fresh)


def scan(review: Path, ideas_dirs: list[Path]) -> None:
    data = load(review)
    added = sum(scan_dir(ideas, data) for ideas in ideas_dirs)
    write_json(manifest_path(review), data)
    say(f"{added} designs added, {len(data['designs'])} in {manifest_path(review)}")
    for d in data["designs"]:
        gaps = [k for k in ("title", "style", "shirt", "idea") if not d.get(k)]
        if gaps:
            say(f"  {d['id']}: fill {', '.join(gaps)}")


# ---------- build ----------


def group_problems(data: dict) -> list[str]:
    used = {d.get("group") for d in data["designs"]}
    unnamed = [g["key"] for g in data["groups"] if g["key"] in used and not g.get("name")]
    keys = {g["key"] for g in data["groups"]}
    stray = [d.get("id") for d in data["designs"] if d.get("group") not in keys]
    named = [f"group {k}: 'name' is empty" for k in unnamed]
    return named + [f"{i}: its group isn't in groups" for i in stray]


def page_problems(data: dict) -> list[str]:
    out = [f"review.json: '{k}' is empty" for k in ("title", "intro") if not data.get(k)]
    ids = [d.get("id") for d in data["designs"]]
    dupes = sorted({i for i in ids if ids.count(i) > 1})
    return out + group_problems(data) + [f"{i}: duplicate id" for i in dupes]


def ref_problems(did: str, refs: list[dict]) -> list[str]:
    out = [
        f"{did}: reference not found: {r.get('file')}"
        for r in refs
        if not Path(r.get("file", "")).is_file()
    ]
    out += [f"{did}: a reference has no caption" for r in refs if not r.get("caption")]
    return out


def design_problems(d: dict) -> list[str]:
    did = d.get("id", "?")
    out = [f"{did}: '{k}' is empty" for k in REQUIRED if not d.get(k)]
    if not ID_SHAPE.fullmatch(did):
        out.append(f"{did}: id must be lowercase letters, digits and hyphens")
    if not HEX.fullmatch(d.get("shirt") or ""):
        out.append(f"{did}: 'shirt' must be a #rrggbb hex")
    if not Path(d.get("file", "")).is_file():
        out.append(f"{did}: print file not found: {d.get('file')}")
    return out + ref_problems(did, d.get("refs", []))


def write_images(src: Path, big: Path, small: Path, sizes: tuple[tuple, tuple]) -> tuple[int, int]:
    """Write a large and a thumbnail copy of src unless both are current; return the large size.

    WebP keeps the print's transparency; references go to JPEG.
    """
    if any(not p.exists() or p.stat().st_mtime < src.stat().st_mtime for p in (big, small)):
        webp = big.suffix == ".webp"
        im = Image.open(src).convert("RGBA" if webp else "RGB")
        for dst, size in zip((big, small), sizes, strict=True):
            im.thumbnail(size, Image.LANCZOS)
            im.save(dst, "WEBP", quality=88, method=4) if webp else im.save(dst, "JPEG", quality=86)
    with Image.open(big) as im:
        return im.size


def ref_key(path: Path) -> str:
    full = str(path.resolve()).lower()
    return slug(path.stem)[:40] + "-" + hashlib.sha1(full.encode()).hexdigest()[:6]


def page_ref(site: Path, r: dict) -> dict:
    src = Path(r["file"])
    key = ref_key(src)
    big, small = site / "r" / f"{key}.jpg", site / "r" / f"{key}-s.jpg"
    w, h = write_images(src, big, small, (REF_MAX, REF_THUMB))
    return {
        "kind": r.get("kind") or "Style reference",
        "caption": r["caption"],
        "link": r.get("link"),
        "img": f"r/{key}.jpg",
        "thumb": f"r/{key}-s.jpg",
        "w": w,
        "h": h,
    }


def page_design(site: Path, d: dict, group_name: str) -> dict:
    src = Path(d["file"])
    big, small = site / "d" / f"{d['id']}.webp", site / "d" / f"{d['id']}-s.webp"
    w, h = write_images(src, big, small, (DESIGN_MAX, DESIGN_THUMB))
    keep = ("id", "group", "sub", "n", "title", "style", "shirt", "shirtName", "idea", "folder")
    return {
        **{k: d.get(k, "") for k in keep},
        "groupName": group_name,
        "design": f"d/{d['id']}.webp",
        "thumb": f"d/{d['id']}-s.webp",
        "w": w,
        "h": h,
        "refs": [page_ref(site, r) for r in d.get("refs", [])],
    }


def batches(site: Path, html: Path) -> list[list[str]]:
    """Split the supporting files into publish calls that fit the Artifact limits."""
    files = sorted(p for p in site.rglob("*") if p.is_file() and p != html)
    big = [p for p in files if p.stat().st_size > FILE_BYTES]
    if big:
        raise SystemExit(f"over 16 MB, lower DESIGN_MAX or REF_MAX: {big}")
    out, size = [[]], 0
    for p in files:
        n = p.stat().st_size
        if batch_full(out[-1], size + n):
            out.append([])
            size = 0
        out[-1].append(p.relative_to(site).as_posix())
        size += n
    return out


def batch_full(batch: list[str], size_with_next: int) -> bool:
    return bool(batch) and (len(batch) >= BATCH_FILES or size_with_next > BATCH_BYTES)


def write_page(review: Path, data: dict, designs: list[dict]) -> Path:
    used = {d["group"] for d in designs}
    page = {
        "title": data["title"],
        "intro": data["intro"],
        "storageKey": "design-review-" + slug(review.name),
        "groups": [g for g in data["groups"] if g["key"] in used],
        "designs": designs,
    }
    blob = json.dumps(page, ensure_ascii=False).replace("<", "\\u003c")
    title = data["title"].replace("&", "&amp;").replace("<", "&lt;")
    html = review / "site" / "design-review.html"
    tpl = TEMPLATE.read_text(encoding="utf8")
    html.write_bytes(tpl.replace("__TITLE__", title).replace("__DATA__", blob).encode("utf8"))
    return html


def build(review: Path) -> None:
    data = load(review)
    issues = page_problems(data) + [p for d in data["designs"] for p in design_problems(d)]
    if issues:
        say("Fix these in review.json, then build again:\n  " + "\n  ".join(issues))
        raise SystemExit(1)
    site = review / "site"
    (site / "d").mkdir(parents=True, exist_ok=True)
    (site / "r").mkdir(parents=True, exist_ok=True)
    names = {g["key"]: g["name"] for g in data["groups"]}
    designs = [page_design(site, d, names[d["group"]]) for d in data["designs"]]
    html = write_page(review, data, designs)
    plan = batches(site, html)
    write_json(review / "publish-batches.json", plan)
    total = sum(p.stat().st_size for p in site.rglob("*") if p.is_file())
    refs = len({r["img"] for d in designs for r in d["refs"]})
    say(f"{len(designs)} designs, {refs} references, {total / 1e6:.1f} MB")
    say(f"page: {html}")
    sizes = ", ".join(f"{len(b)} files" for b in plan)
    say(f"{len(plan)} publish batch(es) in {review / 'publish-batches.json'}: {sizes}")


# ---------- results ----------


def read_rows(rows_file: Path) -> dict[str, dict]:
    """Rows are the JSON lines ({"id", "data"}) an ArtifactData list prints."""
    rows = {}
    for raw in rows_file.read_text(encoding="utf8").splitlines():
        line = raw.strip()
        if line.startswith("{"):
            row = json.loads(line)
            rows[row.get("id")] = row.get("data", {})
    return rows


def result_record(d: dict, tag: dict) -> dict:
    verdict = tag.get("verdict")
    return {
        "id": d["id"],
        "verdict": verdict if verdict in VERDICTS else "untagged",
        "note": tag.get("note", ""),
        "title": d["title"],
        "file": d["file"],
        "folder": d.get("folder", ""),
        "shirt": d["shirt"],
        "shirtName": d["shirtName"],
        "at": tag.get("at"),
    }


def keep_last_round(review: Path) -> None:
    current = review / "review-results.json"
    if current.exists():
        rounds = len(list(review.glob("review-results-round*.json")))
        current.replace(review / f"review-results-round{rounds + 1}.json")


def results(review: Path, rows_file: Path) -> None:
    rows = read_rows(rows_file)
    recs = [result_record(d, rows.get(d["id"], {})) for d in load(review)["designs"]]
    keep_last_round(review)
    write_json(review / "review-results.json", recs)
    order = (*VERDICTS, "untagged")
    counts = ", ".join(f"{sum(r['verdict'] == v for r in recs)} {v}" for v in order)
    say(f"{counts}  ->  {review / 'review-results.json'}")
    for v in order:
        say_verdict(v, [r for r in recs if r["verdict"] == v])


def say_verdict(verdict: str, recs: list[dict]) -> None:
    if recs:
        say(f"\n{verdict.upper()}")
    for r in recs:
        note = f"  | note: {r['note']}" if r["note"] else ""
        say(f"  {r['id']}  {r['title']}{note}")


# ---------- iterate ----------


def revision_number(folder: Path, stem: str) -> int:
    """The revision about to be made: one more than the versions already archived."""
    return len(list((folder / "rejected").glob(f"{stem}-v*.png"))) + 1


def revision_brief(rec: dict) -> Path:
    png = Path(rec["file"])
    folder = png.parents[1]
    number = revision_number(folder, png.stem)
    fields = {
        "SLUG": png.stem,
        "N": str(number),
        "NOTE": " ".join(rec["note"].split()),
        "FOLDER": str(folder),
        "FILE": png.name,
        "SHIRT": f"{rec['shirtName']} ({rec['shirt']})",
        "REPO": str(REPO),
    }
    page = REVISION_BRIEF.read_text(encoding="utf8")
    for key, value in fields.items():
        page = page.replace(f"__{key}__", value)
    out = folder / f"revision-{number}.md"
    out.write_bytes(page.encode("utf8"))
    return out


def iterate(review: Path) -> None:
    path = review / "review-results.json"
    if not path.exists():
        sys.exit(f"{path} is missing; run results first")
    recs = [r for r in json.loads(path.read_text(encoding="utf8")) if r["verdict"] == "iterate"]
    for rec in recs:
        if not rec.get("note"):
            say(f"  {rec['id']}: no note, so no brief; ask the seller what to change")
        elif not Path(rec["file"]).exists():
            say(f"  {rec['id']}: {rec['file']} is missing")
        else:
            say(str(revision_brief(rec)))


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("scan")
    p.add_argument("review", type=Path)
    p.add_argument("ideas", type=Path, nargs="+")
    p = sub.add_parser("build")
    p.add_argument("review", type=Path)
    p = sub.add_parser("results")
    p.add_argument("review", type=Path)
    p.add_argument("rows", type=Path)
    p = sub.add_parser("iterate")
    p.add_argument("review", type=Path)
    a = parser.parse_args()
    if a.cmd == "scan":
        scan(a.review, a.ideas)
    elif a.cmd == "build":
        build(a.review)
    elif a.cmd == "results":
        results(a.review, a.rows)
    else:
        iterate(a.review)


if __name__ == "__main__":
    main()

"""Ingests a batch of exported mockup-template photos into ready-to-use PNGs.

Standalone helper, not part of the `etsy_listings` package -- run it directly
(`uv run python scripts/ingest_mockup_templates.py ...`) against the raw
export from a mockup design tool. It never touches a workspace; it just
produces files for you to drop into `mockup-templates/<name>/` yourself.

Input is a zip file or a directory containing PNGs named:

    {design} - {color}.png
    {design} - {color} - Text.png

Every matching pair is alpha-composited (Text over the base photo) and
written to the output directory as `{prefix}-{slugified color}.png`.

A file whose color segment is "Source Image" (case-insensitive) is a
reference image some export tools include and is skipped without error.
Any other file that can't be paired -- a base photo with no Text overlay, a
Text overlay with no base photo, or a pair whose dimensions don't match --
is a hard error. Every such problem is collected and reported together
before anything is written, rather than failing on the first one found.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

TEXT_SUFFIX = " - Text"
SOURCE_IMAGE_COLOR = "source image"

_CYGDRIVE = re.compile(r"^/cygdrive/([a-zA-Z])(/.*)?$")


def to_native_path(value: str) -> Path:
    """Best-effort conversion of a POSIX-style (Cygwin) path to a native one.

    This is a Windows-native Python invoked from a Cygwin shell (see
    CLAUDE.md), so a path typed as ``/home/Admin/export.zip`` must be
    translated before ``Path`` ever sees it -- otherwise it reads as a
    literal ``\\home\\Admin\\export.zip`` relative to the current drive.
    No-op on non-Windows and for anything that isn't POSIX-absolute.
    """
    if os.name != "nt" or not value.startswith("/"):
        return Path(value)

    cygdrive = _CYGDRIVE.match(value)
    if cygdrive is not None:
        drive, rest = cygdrive.groups()
        return Path(f"{drive.upper()}:\\") / (rest or "").lstrip("/")

    cygpath = shutil.which("cygpath")
    if cygpath is None:
        return Path(value)
    try:
        result = subprocess.run(
            [cygpath, "-w", value],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return Path(value)
    translated = result.stdout.strip()
    if result.returncode != 0 or not translated:
        return Path(value)
    return Path(translated)


@dataclass(frozen=True)
class Pair:
    color: str
    base_path: Path
    text_path: Path


def slugify(color: str) -> str:
    return re.sub(r"\s+", "-", color.strip().lower())


def split_color(stem: str) -> str:
    return stem.rsplit(" - ", 1)[-1]


def find_pngs(root: Path) -> list[Path]:
    return sorted(
        p for p in root.rglob("*.png") if "__MACOSX" not in p.parts and not p.name.startswith(".")
    )


def collect_pairs(root: Path) -> list[Pair]:
    base_files: dict[str, Path] = {}
    text_files: dict[str, Path] = {}

    for path in find_pngs(root):
        stem = path.stem
        is_text = stem.lower().endswith(TEXT_SUFFIX.lower())
        core = stem[: -len(TEXT_SUFFIX)] if is_text else stem

        color = split_color(core)
        if color.strip().lower() == SOURCE_IMAGE_COLOR:
            continue

        bucket = text_files if is_text else base_files
        if core in bucket:
            raise SystemExit(f"Duplicate file for '{core}': '{bucket[core]}' and '{path}'")
        bucket[core] = path

    errors: list[str] = []
    for core in sorted(set(base_files) | set(text_files)):
        if core in base_files and core not in text_files:
            errors.append(f"'{base_files[core].name}' has no matching Text overlay")
        elif core in text_files and core not in base_files:
            errors.append(f"'{text_files[core].name}' has no matching base photo")

    pairs = []
    for core in sorted(set(base_files) & set(text_files)):
        base_path, text_path = base_files[core], text_files[core]
        with Image.open(base_path) as base_img, Image.open(text_path) as text_img:
            if base_img.size != text_img.size:
                errors.append(
                    f"'{base_path.name}' is {base_img.size} but "
                    f"'{text_path.name}' is {text_img.size}"
                )
                continue
        pairs.append(Pair(color=split_color(core), base_path=base_path, text_path=text_path))

    if errors:
        raise SystemExit("Cannot ingest:\n" + "\n".join(f"  - {e}" for e in errors))

    return pairs


def render_pair(pair: Pair, output_dir: Path, prefix: str) -> Path:
    with Image.open(pair.base_path) as base_img, Image.open(pair.text_path) as text_img:
        composited = Image.alpha_composite(base_img.convert("RGBA"), text_img.convert("RGBA"))
    output_path = output_dir / f"{prefix}-{slugify(pair.color)}.png"
    composited.save(output_path)
    return output_path


def ingest_from(root: Path, output_dir: Path, prefix: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    pairs = collect_pairs(root)
    for pair in pairs:
        output_path = render_pair(pair, output_dir, prefix)
        print(f"Wrote {output_path}")
    print(f"Processed {len(pairs)} color(s).")


def ingest(input_path: Path, output_dir: Path, prefix: str) -> None:
    if input_path.is_dir():
        ingest_from(input_path, output_dir, prefix)
        return

    with TemporaryDirectory() as tmp, zipfile.ZipFile(input_path) as zf:
        zf.extractall(tmp)
        ingest_from(Path(tmp), output_dir, prefix)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("input", help="Zip file or directory of exported PNGs")
    parser.add_argument("--output-dir", required=True, help="Where to write the composited PNGs")
    parser.add_argument(
        "--prefix", required=True, help="Output filename prefix, e.g. 'flat-lay-01'"
    )
    args = parser.parse_args()

    input_path = to_native_path(args.input)
    output_dir = to_native_path(args.output_dir)

    if not input_path.exists():
        parser.error(f"input path does not exist: {input_path}")

    ingest(input_path, output_dir, args.prefix)


if __name__ == "__main__":
    main()

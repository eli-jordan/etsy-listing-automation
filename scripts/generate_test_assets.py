"""Generates the synthetic, procedurally-created assets this repo needs
because no real design files or mockup photography exist on this machine:

- A grid/ruler test design (PRD: "a toggle switches to a grid/ruler target,
  which makes warp and displacement errors more obvious than artwork does").
  Used both as the calibrator's bundled test design and as golden-test input.
- A tiny two-colour synthetic mockup template set ("synthetic-tee") standing
  in for real garment photography in golden and behaviour tests.

Run with ``uv run python scripts/generate_test_assets.py``. Output is
committed -- these are deterministic generators, but re-running them should
reproduce byte-identical files (fixed seed, no clock/timestamp inputs), so
regenerating is safe and traceable in a diff.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).parent.parent
DESIGN_SIZE = (360, 432)  # matches the fixture profile's 5:6 print-area aspect
TEMPLATE_SIZE = (480, 576)

# Corner markers, distinct colours, to make orientation obvious after a warp.
CORNER_COLOURS = {
    "top-left": (220, 40, 40, 255),
    "top-right": (40, 160, 60, 255),
    "bottom-right": (40, 90, 220, 255),
    "bottom-left": (230, 190, 30, 255),
}


def make_grid_target(size: tuple[int, int]) -> Image.Image:
    w, h = size
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    draw.rectangle([0, 0, w - 1, h - 1], outline=(20, 20, 20, 255), width=4)

    step = 24
    for x in range(step, w, step):
        major = (x % (step * 5)) == 0
        colour = (60, 60, 60, 200) if major else (150, 150, 150, 120)
        draw.line([(x, 0), (x, h)], fill=colour, width=2 if major else 1)
    for y in range(step, h, step):
        major = (y % (step * 5)) == 0
        colour = (60, 60, 60, 200) if major else (150, 150, 150, 120)
        draw.line([(0, y), (w, y)], fill=colour, width=2 if major else 1)

    marker = 28
    draw.rectangle([0, 0, marker, marker], fill=CORNER_COLOURS["top-left"])
    draw.rectangle([w - marker, 0, w, marker], fill=CORNER_COLOURS["top-right"])
    draw.rectangle([w - marker, h - marker, w, h], fill=CORNER_COLOURS["bottom-right"])
    draw.rectangle([0, h - marker, marker, h], fill=CORNER_COLOURS["bottom-left"])

    cx, cy = w // 2, h // 2
    draw.ellipse([cx - 40, cy - 40, cx + 40, cy + 40], outline=(180, 30, 120, 255), width=3)
    draw.line([(cx, 0), (cx, h)], fill=(180, 30, 120, 90), width=1)
    draw.line([(0, cy), (w, cy)], fill=(180, 30, 120, 90), width=1)

    return image


def make_template_base(size: tuple[int, int], garment_rgb: tuple[int, int, int]) -> Image.Image:
    """A flat-lay-style base: solid garment colour on a neutral backdrop, with a
    soft vertical gradient across the chest so luminance/height maps derived
    from it are non-trivial (real photography always has some falloff)."""
    w, h = size
    backdrop = np.full((h, w, 3), 235, dtype=np.uint8)

    margin_x, margin_top, margin_bottom = int(w * 0.12), int(h * 0.08), int(h * 0.1)
    garment = backdrop.copy()
    y0, y1 = margin_top, h - margin_bottom
    x0, x1 = margin_x, w - margin_x

    gradient = np.linspace(0.85, 1.15, y1 - y0, dtype=np.float32)
    for i, factor in enumerate(gradient):
        row = np.clip(np.array(garment_rgb, dtype=np.float32) * factor, 0, 255).astype(np.uint8)
        garment[y0 + i, x0:x1] = row

    # Rounded-ish shoulders: fade the top corners of the garment region back to backdrop.
    fade = int((y1 - y0) * 0.08)
    for i in range(fade):
        alpha = i / fade
        blend_row = (
            garment[y0 + i, x0:x1].astype(np.float32) * alpha
            + backdrop[y0 + i, x0:x1].astype(np.float32) * (1 - alpha)
        ).astype(np.uint8)
        garment[y0 + i, x0:x1] = blend_row

    return Image.fromarray(garment, mode="RGB")


def print_area_quad(size: tuple[int, int]) -> list[list[float]]:
    """A quad noticeably inset and slightly non-rectangular (a hair of
    perspective skew), so warp tests exercise more than an axis-aligned resize."""
    w, h = size
    return [
        [w * 0.30, h * 0.22],
        [w * 0.72, h * 0.20],
        [w * 0.74, h * 0.68],
        [w * 0.28, h * 0.70],
    ]


def main() -> None:
    design_dir = REPO_ROOT / "tests" / "fixtures" / "render"
    design_dir.mkdir(parents=True, exist_ok=True)
    grid = make_grid_target(DESIGN_SIZE)
    grid.save(design_dir / "grid-target.png", format="PNG", optimize=False, compress_level=6)

    bundled_dir = REPO_ROOT / "src" / "etsy_listings" / "ui" / "api" / "static"
    bundled_dir.mkdir(parents=True, exist_ok=True)
    grid.save(
        bundled_dir / "bundled-test-design.png", format="PNG", optimize=False, compress_level=6
    )

    template_dir = REPO_ROOT / "tests" / "fixtures" / "mockup-templates" / "synthetic-tee"
    template_dir.mkdir(parents=True, exist_ok=True)
    colours = {"black": (35, 35, 38), "white": (245, 245, 240)}
    for name, rgb in colours.items():
        base = make_template_base(TEMPLATE_SIZE, rgb)
        base.save(template_dir / f"{name}.png", format="PNG", optimize=False, compress_level=6)

    quad = print_area_quad(TEMPLATE_SIZE)
    template_yaml = template_dir / "template.yaml"
    quad_yaml = "\n".join(f"    - [{p[0]}, {p[1]}]" for p in quad)
    template_yaml.write_text(
        "warp:\n  quad:\n" + quad_yaml + "\n"
        "displace:\n  enabled: false\n  strength: 0.0\n"
        "shade:\n  enabled: true\n  opacity: 0.6\n  blend: soft-light\n",
        encoding="utf-8",
    )

    print(f"wrote {design_dir / 'grid-target.png'}")
    print(f"wrote {bundled_dir / 'bundled-test-design.png'}")
    print(f"wrote {template_dir} (black.png, white.png, template.yaml)")


if __name__ == "__main__":
    main()

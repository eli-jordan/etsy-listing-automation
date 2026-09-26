"""Generates the synthetic, procedurally-created assets this repo needs
because no real design files or mockup photography exist on this machine:

- A grid/ruler test design (PRD: "a toggle switches to a grid/ruler target,
  which makes warp and displacement errors more obvious than artwork does").
  Used both as the calibrator's bundled test design and as golden-test input.
- Dark-ink and light-ink bundled test designs, so a mis-resolved artwork
  (light-ink design on a light garment, say) is visually obvious in the
  calibrator rather than only described in a diff.
- Tiny synthetic mockup template sets standing in for real garment
  photography in golden and behaviour tests -- ``colour-matrix`` kind
  (``synthetic-tee``, ``flat-lay-01``) and ``multiple`` kind
  (``colour-chart-01``).
- Tiny clips for the video gate (PRD 71) under ``tests/fixtures/video/``: one
  that passes every rule, one per rule a probe can fail on (too short, too
  small, an audio track, audio but no picture), and a PNG renamed ``.mp4``.

Run with ``uv run python scripts/generate_test_assets.py``. Output is
committed -- these are deterministic generators, but re-running them should
reproduce byte-identical files (fixed seed, no clock/timestamp inputs), so
regenerating is safe and traceable in a diff.
"""

from __future__ import annotations

from pathlib import Path

import av
import numpy as np
import yaml
from PIL import Image, ImageDraw

REPO_ROOT = Path(__file__).parent.parent
DESIGN_SIZE = (360, 432)  # matches the fixture garment profile's 5:6 print-area aspect
TEMPLATE_SIZE = (480, 576)
CHART_SIZE = (960, 576)  # two garments side by side
VIDEO_FPS = 10
"""Low on purpose: a clip's duration is its frame count over this, and fewer
frames keep a committed fixture a few KB."""
AUDIO_RATE = 8000

# Corner markers, distinct colours, to make orientation obvious after a warp.
CORNER_COLOURS = {
    "top-left": (220, 40, 40, 255),
    "top-right": (40, 160, 60, 255),
    "bottom-right": (40, 90, 220, 255),
    "bottom-left": (230, 190, 30, 255),
}


def make_grid_target(
    size: tuple[int, int], *, line_rgb: tuple[int, int, int] | None = None
) -> Image.Image:
    """``line_rgb`` swaps the grid/outline ink colour: default (near-black) for
    the general-purpose target, dark or light for the artwork-tone targets."""
    w, h = size
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    outline = (*line_rgb, 255) if line_rgb else (20, 20, 20, 255)
    draw.rectangle([0, 0, w - 1, h - 1], outline=outline, width=4)

    step = 24
    for x in range(step, w, step):
        major = (x % (step * 5)) == 0
        colour = (
            (*line_rgb, 200) if line_rgb else ((60, 60, 60, 200) if major else (150, 150, 150, 120))
        )
        draw.line([(x, 0), (x, h)], fill=colour, width=2 if major else 1)
    for y in range(step, h, step):
        major = (y % (step * 5)) == 0
        colour = (
            (*line_rgb, 200) if line_rgb else ((60, 60, 60, 200) if major else (150, 150, 150, 120))
        )
        draw.line([(0, y), (w, y)], fill=colour, width=2 if major else 1)

    marker = 28
    draw.rectangle([0, 0, marker, marker], fill=CORNER_COLOURS["top-left"])
    draw.rectangle([w - marker, 0, w, marker], fill=CORNER_COLOURS["top-right"])
    draw.rectangle([w - marker, h - marker, w, h], fill=CORNER_COLOURS["bottom-right"])
    draw.rectangle([0, h - marker, marker, h], fill=CORNER_COLOURS["bottom-left"])

    cx, cy = w // 2, h // 2
    ring = (*line_rgb, 255) if line_rgb else (180, 30, 120, 255)
    draw.ellipse([cx - 40, cy - 40, cx + 40, cy + 40], outline=ring, width=3)
    if not line_rgb:
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


def print_area_box(size: tuple[int, int], *, x_offset: float = 0.0) -> list[dict[str, float]]:
    """A box noticeably inset and slightly non-rectangular (a hair of
    perspective skew), so warp tests exercise more than an axis-aligned
    resize. ``x_offset`` (0..1 of width) lets a chart scene place several
    boxes side by side without overlapping."""
    w, h = size
    ox = w * x_offset
    return [
        {"x": ox + w * 0.30, "y": h * 0.22},
        {"x": ox + w * 0.72, "y": h * 0.20},
        {"x": ox + w * 0.74, "y": h * 0.68},
        {"x": ox + w * 0.28, "y": h * 0.70},
    ]


def main() -> None:
    design_dir = REPO_ROOT / "tests" / "fixtures" / "render"
    design_dir.mkdir(parents=True, exist_ok=True)
    grid = make_grid_target(DESIGN_SIZE)
    grid.save(design_dir / "grid-target.png", format="PNG", optimize=False, compress_level=6)

    on_light = make_grid_target(DESIGN_SIZE, line_rgb=(15, 15, 15))  # dark ink, for light garments
    on_dark = make_grid_target(
        DESIGN_SIZE, line_rgb=(245, 245, 245)
    )  # light ink, for dark garments

    bundled_dir = REPO_ROOT / "src" / "etsy_listings" / "ui" / "api" / "static"
    bundled_dir.mkdir(parents=True, exist_ok=True)
    grid.save(
        bundled_dir / "bundled-test-design.png", format="PNG", optimize=False, compress_level=6
    )
    on_light.save(
        bundled_dir / "bundled-test-design-on-light.png",
        format="PNG",
        optimize=False,
        compress_level=6,
    )
    on_dark.save(
        bundled_dir / "bundled-test-design-on-dark.png",
        format="PNG",
        optimize=False,
        compress_level=6,
    )

    _write_colour_matrix_set(
        REPO_ROOT / "tests" / "fixtures" / "mockup-templates" / "synthetic-tee",
        {"black": (35, 35, 38), "white": (245, 245, 240)},
    )

    # Matches tests/fixtures/workspace's garment profile (templates: [flat-lay-01]) and
    # listing (colors: [black, blue-jean, ivory, moss]) -- lets the render
    # stage's behaviour tests exercise a full listing end to end.
    _write_colour_matrix_set(
        REPO_ROOT / "tests" / "fixtures" / "workspace" / "mockup-templates" / "flat-lay-01",
        {
            "black": (35, 35, 38),
            "blue-jean": (72, 96, 130),
            "ivory": (230, 222, 200),
            "moss": (100, 110, 70),
        },
    )

    _write_multiple_set(
        REPO_ROOT / "tests" / "fixtures" / "workspace" / "mockup-templates" / "colour-chart-01",
        {"black": (35, 35, 38), "moss": (100, 110, 70)},
    )

    design_dest = REPO_ROOT / "tests" / "fixtures" / "workspace" / "designs" / "take-a-hike.png"
    design_dest.parent.mkdir(parents=True, exist_ok=True)
    grid.save(design_dest, format="PNG", optimize=False, compress_level=6)

    _write_video_clips(REPO_ROOT / "tests" / "fixtures" / "video", grid)

    print(f"wrote {design_dir / 'grid-target.png'}")
    print(f"wrote {bundled_dir / 'bundled-test-design.png'}")
    print(f"wrote {bundled_dir / 'bundled-test-design-on-light.png'}")
    print(f"wrote {bundled_dir / 'bundled-test-design-on-dark.png'}")
    print(f"wrote {design_dest}")


def _write_colour_matrix_set(template_dir: Path, colours: dict[str, tuple[int, int, int]]) -> None:
    template_dir.mkdir(parents=True, exist_ok=True)
    for name, rgb in colours.items():
        base = make_template_base(TEMPLATE_SIZE, rgb)
        base.save(template_dir / f"{name}.png", format="PNG", optimize=False, compress_level=6)

    config = {
        "kind": "colour-matrix",
        "bounding_box": print_area_box(TEMPLATE_SIZE),
        "shade": {"enabled": True, "opacity": 0.6, "blend": "soft-light"},
    }
    (template_dir / "template.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    print(f"wrote {template_dir} ({', '.join(colours)}, template.yaml)")


def _write_multiple_set(template_dir: Path, colours: dict[str, tuple[int, int, int]]) -> None:
    """One photo, several garments side by side -- ``multiple`` kind."""
    template_dir.mkdir(parents=True, exist_ok=True)
    w, h = CHART_SIZE
    scene = np.full((h, w, 3), 235, dtype=np.uint8)
    names = list(colours)
    slot_w = w // len(names)
    placements = []
    for i, name in enumerate(names):
        rgb = colours[name]
        slot = make_template_base((slot_w, h), rgb)
        scene[:, i * slot_w : (i + 1) * slot_w] = np.asarray(slot)
        placements.append({"colour": name, "bounding_box": print_area_box((slot_w, h), x_offset=i)})

    Image.fromarray(scene, mode="RGB").save(
        template_dir / "scene.png", format="PNG", optimize=False, compress_level=6
    )

    config = {
        "kind": "multiple",
        "colour_coverage": "subset",
        "shade": {"enabled": True, "opacity": 0.6, "blend": "soft-light"},
        "placements": placements,
    }
    (template_dir / "template.yaml").write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8"
    )
    print(f"wrote {template_dir} ({', '.join(colours)}, template.yaml)")


def _write_video_clips(video_dir: Path, grid: Image.Image) -> None:
    """The video gate's fixtures (PRD 71). The good clip clears each rule by a
    little -- 3.2 s against 3 s, 512 px against 500 -- so each failing one
    differs from it in exactly one fact."""
    video_dir.mkdir(parents=True, exist_ok=True)
    clips = {
        "valid-3s-512.mp4": {"size": (512, 512), "seconds": 3.2},
        "short-2s-512.mp4": {"size": (512, 512), "seconds": 2.0},
        "small-3s-400.mp4": {"size": (400, 400), "seconds": 3.2},
        "with-audio-3s-512.mp4": {"size": (512, 512), "seconds": 3.2, "audio": True},
        "audio-only-3s.mp4": {"size": None, "seconds": 3.2, "audio": True},
    }
    for name, spec in clips.items():
        _write_clip(video_dir / name, **spec)  # type: ignore[arg-type]
        print(f"wrote {video_dir / name}")
    # Not a video at all: Etsy answers a bare 500 for one (decision 9).
    grid.save(video_dir / "png-renamed.mp4", format="PNG", optimize=False, compress_level=6)
    print(f"wrote {video_dir / 'png-renamed.mp4'}")


def _write_clip(
    path: Path, *, size: tuple[int, int] | None, seconds: float, audio: bool = False
) -> None:
    """H.264 (and AAC) in MP4, byte-for-byte reproducible: ``bitexact`` keeps
    the muxer from stamping a creation time or encoder string, one encoder
    thread keeps x264's output order fixed, and every frame is the same
    constant picture -- which is also what makes a 3 s clip a few KB."""
    with av.open(str(path), "w", format="mp4", options={"fflags": "+bitexact"}) as container:
        video = None
        if size is not None:
            video = container.add_stream("libx264", rate=VIDEO_FPS)
            video.width, video.height = size
            video.pix_fmt = "yuv420p"
            video.options = {"preset": "ultrafast", "crf": "45", "threads": "1"}
        sound = container.add_stream("aac", rate=AUDIO_RATE) if audio else None
        if sound is not None:
            sound.layout = "mono"

        if video is not None and size is not None:
            picture = np.zeros((size[1], size[0], 3), dtype=np.uint8)
            picture[:, :] = (72, 96, 130)
            for index in range(round(seconds * VIDEO_FPS)):
                frame = av.VideoFrame.from_ndarray(picture, format="rgb24")
                frame.pts = index
                container.mux(video.encode(frame))
            container.mux(video.encode(None))

        if sound is not None:
            total = round(seconds * AUDIO_RATE)
            silence = np.zeros((1, 1024), dtype=np.float32)
            for start in range(0, total, 1024):
                chunk = silence[:, : min(1024, total - start)]
                samples = av.AudioFrame.from_ndarray(chunk, format="fltp", layout="mono")
                samples.sample_rate = AUDIO_RATE
                samples.pts = start
                container.mux(sound.encode(samples))
            container.mux(sound.encode(None))


if __name__ == "__main__":
    main()

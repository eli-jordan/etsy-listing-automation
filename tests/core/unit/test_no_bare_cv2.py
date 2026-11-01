"""Cheap insurance (plan.md risk 5): every ``cv2`` call that does geometric
resampling must pass explicit ``interpolation``/``borderMode`` rather than
relying on defaults, since those defaults are not guaranteed stable across
OpenCV versions. A grep is far cheaper than a flaky cross-version golden."""

from __future__ import annotations

import re
from pathlib import Path

RENDER_SRC = Path(__file__).parents[3] / "src" / "etsy_listings" / "core" / "render"

RESAMPLING_CALLS = {
    # warpPerspective/warpAffine take the interpolation *flag* via `flags=`,
    # not a separate `interpolation=` kwarg -- `remap` is the odd one out.
    "cv2.warpPerspective": ("flags", "borderMode"),
    "cv2.remap": ("interpolation", "borderMode"),
    "cv2.warpAffine": ("flags", "borderMode"),
    "cv2.GaussianBlur": ("borderType",),
    "cv2.Sobel": ("borderType",),
}


def _call_arguments(text: str, start: int) -> str:
    """The text from *start* (just past a call's opening parenthesis) up to and
    including its matching closing parenthesis."""
    depth = 1
    end = start
    while depth > 0 and end < len(text):
        if text[end] == "(":
            depth += 1
        elif text[end] == ")":
            depth -= 1
        end += 1
    return text[start:end]


def _violations(path: Path, call: str, required_kwargs: tuple[str, ...]) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return [
        f"{path.relative_to(RENDER_SRC.parent.parent.parent)}: "
        f"{call}(...) is missing explicit {kwarg}="
        for match in re.finditer(re.escape(call) + r"\(", text)
        for kwarg in required_kwargs
        if kwarg not in _call_arguments(text, match.end())
    ]


def test_every_resampling_cv2_call_has_explicit_interpolation_and_border_args() -> None:
    violations = [
        violation
        for path in RENDER_SRC.rglob("*.py")
        for call, required_kwargs in RESAMPLING_CALLS.items()
        for violation in _violations(path, call, required_kwargs)
    ]
    assert not violations, "\n".join(violations)

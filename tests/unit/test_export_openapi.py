"""`scripts/export_openapi.py`: the committed contract (ADR-0011) must not
depend on whether this checkout happens to have a built SPA.

The SPA fallback route only exists when the built frontend does, so an export
from a checkout with ``src/ui/dist`` used to gain a ``/{full_path}`` operation
that one without it lacked.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.export_openapi import build_schema

from etsy_listings.ui.api import app as app_module


def _built_spa(root: Path) -> Path:
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<html></html>", encoding="utf-8")
    return root


def test_export_is_identical_with_or_without_a_built_spa(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "FRONTEND_DIST", _built_spa(tmp_path / "dist"))
    with_spa = build_schema()
    monkeypatch.setattr(app_module, "FRONTEND_DIST", tmp_path / "absent")
    without_spa = build_schema()

    assert with_spa == without_spa
    assert not any("full_path" in path for path in with_spa["paths"])

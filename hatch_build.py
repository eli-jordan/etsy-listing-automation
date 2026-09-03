"""Hatchling build hook: builds the calibrator frontend into
``ui/frontend/dist/`` at wheel-build time, but only when it's absent (A5).

A CI-built wheel ships ``dist/`` already, so installing the package doesn't
need node at all -- this hook exists for the case of building from a clean
checkout (``uv build``, or an editable install's first sync) where nobody has
run ``npm run build`` yet.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class FrontendBuildHook(BuildHookInterface):  # type: ignore[type-arg]
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        frontend_dir = Path(self.root) / "src" / "etsy_listings" / "ui" / "frontend"
        dist_dir = frontend_dir / "dist"
        if dist_dir.is_dir():
            return

        npm = shutil.which("npm")
        if npm is None:
            self.app.display_warning(
                "npm not found on PATH; skipping the calibrator frontend build. "
                "The etsy-listings package will still install, but `ui` will "
                "serve no frontend until dist/ exists (run `npm run build` in "
                "src/etsy_listings/ui/frontend manually)."
            )
            return

        self.app.display_info("building calibrator frontend (ui/frontend/dist absent)")
        subprocess.run([npm, "install"], cwd=frontend_dir, check=True)
        subprocess.run([npm, "run", "build"], cwd=frontend_dir, check=True)

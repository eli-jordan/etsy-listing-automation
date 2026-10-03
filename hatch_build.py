"""Hatchling build hook: builds the calibrator frontend into
``ui/frontend/dist/`` from locked dependencies at wheel-build time.

Every release wheel rebuilds its SPA; installing that wheel needs no Node.
Editable installs reuse existing assets or build them when npm is available,
and otherwise allow Python-only development with an actionable warning.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class FrontendBuildHook(BuildHookInterface):  # type: ignore[type-arg]
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        frontend_dir = Path(self.root) / "src" / "etsy_listings" / "ui" / "frontend"
        dist_dir = frontend_dir / "dist"
        # Editable installs may reuse a developer's build. Release wheels must
        # rebuild: directory existence cannot prove which sources made it.
        if version == "editable" and dist_dir.is_dir():
            return

        npm = shutil.which("npm")
        if npm is None:
            if version != "editable":
                raise RuntimeError("npm is required to build current frontend assets for a wheel")
            self.app.display_warning(
                "npm not found on PATH; skipping the calibrator frontend build. "
                "The etsy-listings package will still install, but `ui` will "
                "serve no frontend until dist/ exists (run `npm run build` in "
                "src/etsy_listings/ui/frontend manually)."
            )
            return

        # Cygwin's npm launcher is a shell script, which Windows Python cannot
        # execute. Node's bundled CLI also avoids cmd.exe quoting on Windows.
        command = [npm]
        if sys.platform == "win32":
            node = shutil.which("node")
            cli = Path(npm).parent / "node_modules" / "npm" / "bin" / "npm-cli.js"
            if node is None or not cli.is_file():
                raise RuntimeError(
                    "Node and its bundled npm CLI are required to build the frontend"
                )
            command = [node, str(cli)]
        self.app.display_info("building frontend from package-lock.json")
        subprocess.run([*command, "ci", "--no-audit", "--no-fund"], cwd=frontend_dir, check=True)
        subprocess.run([*command, "run", "build"], cwd=frontend_dir, check=True)

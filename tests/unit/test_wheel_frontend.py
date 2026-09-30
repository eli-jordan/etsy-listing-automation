"""A wheel must carry assets built from its current frontend source."""

import shutil
import subprocess
import zipfile
from pathlib import Path


def test_wheel_rebuilds_existing_frontend_assets(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    shutil.copyfile(root / "hatch_build.py", tmp_path / "hatch_build.py")
    (tmp_path / "pyproject.toml").write_text("""
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
[project]
name = "frontend-wheel-fixture"
version = "0.0.1"
[tool.hatch.build.targets.wheel]
packages = ["src/etsy_listings"]
[tool.hatch.build]
artifacts = ["src/etsy_listings/ui/frontend/dist/**"]
[tool.hatch.build.hooks.custom]
path = "hatch_build.py"
""")
    frontend = tmp_path / "src/etsy_listings/ui/frontend"
    frontend.mkdir(parents=True)
    (tmp_path / "src/etsy_listings/__init__.py").write_text("")
    (frontend / "package.json").write_text("""{"name":"fixture","version":"1.0.0",
"scripts":{"build":"node build.cjs"}}""")
    (frontend / "package-lock.json").write_text("""{"name":"fixture","version":"1.0.0",
"lockfileVersion":3,"packages":{"":{"name":"fixture","version":"1.0.0"}}}""")
    (frontend / "build.cjs").write_text("""const fs = require("fs");
fs.mkdirSync("dist", {recursive: true});
fs.writeFileSync("dist/index.html", fs.readFileSync("source.txt"));""")
    (frontend / "dist").mkdir()
    (frontend / "dist/index.html").write_text("stale frontend")
    (frontend / "source.txt").write_text("current frontend")
    result = subprocess.run(
        [
            shutil.which("uv"),
            "build",
            "--offline",
            "--wheel",
            "--out-dir",
            str(tmp_path / "wheels"),
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    wheel = next((tmp_path / "wheels").glob("*.whl"))
    with zipfile.ZipFile(wheel) as archive:
        assert archive.read("etsy_listings/ui/frontend/dist/index.html") == b"current frontend"

"""Distributions must carry the React application the way a release needs it.

Each test builds a copy of the real project -- its ``pyproject.toml``,
``hatch_build.py``, ``.gitignore`` and Python package -- around a tiny npm
project standing in for ``src/ui``, so the packaging configuration under test
is the one that ships, while the frontend build takes milliseconds.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tarfile
import textwrap
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Where the wheel carries the built SPA, relative to its root.
WHEEL_ASSETS = "etsy_listings/ui/static"

BUILD_SCRIPT = """const fs = require("fs");
const source = fs.readFileSync("source.txt", "utf8");
fs.mkdirSync("dist/assets", {recursive: true});
fs.writeFileSync("dist/index.html",
  `<html><script type="module" src="/assets/app.js"></script>${source}</html>`);
fs.writeFileSync("dist/assets/app.js", `console.log(${JSON.stringify(source)});`);
"""


def _project(tmp_path: Path, *, build_script: str = BUILD_SCRIPT) -> Path:
    """A checkout of the real packaging configuration with a stand-in SPA whose
    ``dist/`` holds stale output that no longer matches its source."""
    project = tmp_path / "project"
    project.mkdir()
    for name in ("pyproject.toml", "hatch_build.py", "README.md", ".gitignore"):
        shutil.copyfile(ROOT / name, project / name)
    shutil.copytree(
        ROOT / "src" / "etsy_listings",
        project / "src" / "etsy_listings",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    ui = project / "src" / "ui"
    (ui / "src").mkdir(parents=True)
    (ui / "package.json").write_text(
        '{"name":"fixture","version":"1.0.0","scripts":{"build":"node build.cjs"}}'
    )
    (ui / "package-lock.json").write_text(
        '{"name":"fixture","version":"1.0.0","lockfileVersion":3,'
        '"packages":{"":{"name":"fixture","version":"1.0.0"}}}'
    )
    (ui / "build.cjs").write_text(build_script)
    (ui / "source.txt").write_text("current frontend")
    (ui / "src" / "main.tsx").write_text("export {};\n")
    (ui / "dist" / "assets").mkdir(parents=True)
    (ui / "dist" / "index.html").write_text("stale frontend")
    (ui / "node_modules" / "left-pad").mkdir(parents=True)
    (ui / "node_modules" / "left-pad" / "index.js").write_text("module.exports = 0;")
    return project


def _uv_build(source: Path, out_dir: Path, *flags: str) -> subprocess.CompletedProcess[str]:
    uv = shutil.which("uv")
    assert uv is not None, "uv is required to build distributions"
    return subprocess.run(
        [uv, "build", "--offline", *flags, "--out-dir", str(out_dir), str(source)],
        capture_output=True,
        text=True,
    )


def _build_wheel(project: Path, out_dir: Path) -> Path:
    result = _uv_build(project, out_dir, "--wheel")
    assert result.returncode == 0, result.stderr
    return next(out_dir.glob("*.whl"))


def test_wheel_rebuilds_stale_assets_from_current_source(tmp_path: Path) -> None:
    wheel = _build_wheel(_project(tmp_path), tmp_path / "wheels")
    with zipfile.ZipFile(wheel) as archive:
        index = archive.read(f"{WHEEL_ASSETS}/index.html").decode()
    assert "current frontend" in index
    assert "stale" not in index


def test_wheel_ships_built_assets_but_no_npm_project(tmp_path: Path) -> None:
    wheel = _build_wheel(_project(tmp_path), tmp_path / "wheels")
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
    assert f"{WHEEL_ASSETS}/assets/app.js" in names
    frontend_source = [
        name
        for name in names
        if "node_modules" in name
        or name.endswith(("package.json", "package-lock.json", ".tsx", "build.cjs"))
        or "/dist/" in name
    ]
    assert frontend_source == []


def test_wheel_build_fails_when_the_frontend_build_emits_no_index(tmp_path: Path) -> None:
    project = _project(tmp_path, build_script="// builds nothing\n")
    shutil.rmtree(project / "src" / "ui" / "dist")
    result = _uv_build(project, tmp_path / "wheels", "--wheel")
    assert result.returncode != 0
    assert "index.html" in result.stderr
    assert not list((tmp_path / "wheels").glob("*.whl"))


def test_sdist_carries_what_a_wheel_build_needs(tmp_path: Path) -> None:
    result = _uv_build(_project(tmp_path), tmp_path / "sdists", "--sdist")
    assert result.returncode == 0, result.stderr
    sdist = next((tmp_path / "sdists").glob("*.tar.gz"))
    with tarfile.open(sdist) as archive:
        names = {name.split("/", 1)[1] for name in archive.getnames() if "/" in name}
    assert {
        "hatch_build.py",
        "pyproject.toml",
        "src/ui/package.json",
        "src/ui/package-lock.json",
        "src/ui/build.cjs",
        "src/ui/source.txt",
        "src/ui/src/main.tsx",
    } <= names
    built_or_installed = [
        name
        for name in names
        if "node_modules" in name or "/dist/" in name or name.endswith("app.js")
    ]
    assert built_or_installed == []

    wheel = _build_wheel(sdist, tmp_path / "wheels")
    with zipfile.ZipFile(wheel) as archive:
        assert "current frontend" in archive.read(f"{WHEEL_ASSETS}/index.html").decode()


SERVE_SCRIPT = textwrap.dedent(
    """
    import re, shutil, sys
    from pathlib import Path

    import etsy_listings
    from fastapi.testclient import TestClient
    from etsy_listings.ui.api.app import create_app
    from etsy_listings.core.workspace.workspace import Workspace

    install, workspace = Path(sys.argv[1]), Path(sys.argv[2])
    assert Path(etsy_listings.__file__).is_relative_to(install), etsy_listings.__file__
    assert shutil.which("node") is None and shutil.which("npm") is None
    client = TestClient(create_app(Workspace.discover(root_override=workspace)))
    for page in ("/", "/listings/some-client-route"):
        index = client.get(page)
        assert index.status_code == 200, (page, index.status_code)
        assert "current frontend" in index.text, index.text
    asset = re.search(r'src="(/assets/[^"]+)"', index.text).group(1)
    served = client.get(asset)
    assert served.status_code == 200 and "current frontend" in served.text, served.text
    print("served")
    """
)


def test_installed_wheel_serves_the_spa_without_node_or_the_checkout(
    tmp_path: Path, workspace_root: Path
) -> None:
    wheel = _build_wheel(_project(tmp_path), tmp_path / "wheels")
    install = tmp_path / "installed"
    uv = shutil.which("uv")
    assert uv is not None
    installed = subprocess.run(
        [uv, "pip", "install", "--offline", "--no-deps", "--target", str(install), str(wheel)],
        capture_output=True,
        text=True,
    )
    assert installed.returncode == 0, installed.stderr
    # The project and its build output are gone: nothing but the installed
    # package can supply the assets.
    shutil.rmtree(tmp_path / "project")

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    env = {
        **os.environ,
        "PYTHONPATH": str(install),
        "PATH": str(Path(sys.executable).parent),
    }
    env.pop("ETSY_LISTINGS_ROOT", None)
    served = subprocess.run(
        [sys.executable, "-c", SERVE_SCRIPT, str(install), str(workspace_root)],
        cwd=elsewhere,
        env=env,
        capture_output=True,
        text=True,
    )
    assert served.returncode == 0, served.stderr
    assert served.stdout.strip() == "served"

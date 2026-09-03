from __future__ import annotations

import shutil
from pathlib import Path

import pytest

FIXTURE_WORKSPACE = Path(__file__).parent / "fixtures" / "workspace"


@pytest.fixture
def workspace_root(tmp_path: Path) -> Path:
    """A writable copy of the fixture workspace, so tests can write lockfiles and
    caches into it without mutating the checked-in fixtures."""
    dest = tmp_path / "workspace"
    shutil.copytree(FIXTURE_WORKSPACE, dest)
    return dest


def pytest_addoption(parser: pytest.Parser) -> None:
    parser.addoption(
        "--update-goldens",
        action="store_true",
        default=False,
        help="Regenerate golden render fixtures instead of comparing against them.",
    )


@pytest.fixture
def update_goldens(request: pytest.FixtureRequest) -> bool:
    value: bool = request.config.getoption("--update-goldens")
    return value

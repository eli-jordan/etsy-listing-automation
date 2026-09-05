from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

import pytest

FIXTURE_WORKSPACE = Path(__file__).parent / "fixtures" / "workspace"

REQUIRE_EVERY_LAYER_ENV_VAR = "ETSY_LISTINGS_REQUIRE_EVERY_LAYER"


@pytest.fixture(scope="session")
def prerequisite_missing() -> Callable[[str], NoReturn]:
    """Skip -- unless the environment insists every layer must run.

    The browser and e2e layers each skip themselves when a prerequisite is
    absent: chromium, a built SPA, a Printify token. That is right on a
    contributor's machine, and wrong in CI, where a layer that quietly runs
    nothing still reports a green tick for work it never did. Setting
    ``ETSY_LISTINGS_REQUIRE_EVERY_LAYER`` turns the skip into a failure
    naming the prerequisite that was missing.
    """

    def _missing(reason: str) -> NoReturn:
        if os.environ.get(REQUIRE_EVERY_LAYER_ENV_VAR):
            pytest.fail(reason, pytrace=False)
        pytest.skip(reason)

    return _missing


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

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

import pytest

from tests.support import scripted as scripted_prompts

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


@pytest.fixture
def scripted(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[scripted_prompts.Answers], scripted_prompts.Scripted]:
    """Answer an interactive command's questions by their text.

    Shared by `setup`'s and `new`'s tests: both are wizards, and neither
    should have its tests pinned to the order it happens to ask in. See
    ``tests/support/scripted.py``.
    """

    def install(answers: scripted_prompts.Answers) -> scripted_prompts.Scripted:
        return scripted_prompts.install(monkeypatch, answers)

    return install


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


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Leave the opt-in `capture` scenes out unless `-m` asks for them.

    They are browser tests by location, so a plain `-m browser` would otherwise
    run them; but they only write review screenshots and assert nothing a
    regression could break (T11). Naming the marker -- `-m capture` -- is the
    one way in.
    """
    if "capture" in (config.getoption("markexpr") or ""):
        return
    kept = [item for item in items if item.get_closest_marker("capture") is None]
    if len(kept) != len(items):
        config.hook.pytest_deselected(items=[i for i in items if i not in kept])
        items[:] = kept

"""A saved listing's gallery scenes are composed in the background, into the
scene cache the Listing Images tab's previews read."""

from __future__ import annotations

import logging
import threading
from pathlib import Path

import pytest

from etsy_listings.core.application.refusals import TemplateMissing
from etsy_listings.core.application.scene_warming import Scene, SceneWarmer
from etsy_listings.core.workspace.workspace import Workspace

from tests.support.builders import FIXTURE_LISTING, edit_listing
from tests.support.scenes import expected_scene

DESIGN = "designs/take-a-hike.png"
WAIT = 30.0


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    return Workspace.discover(root_override=workspace_root)


def _cached(workspace: Workspace) -> set[bytes]:
    root = workspace.scene_cache_dir()
    return {path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _warmed(warmer: SceneWarmer, *names: str) -> None:
    warmer.start()
    try:
        for name in names:
            warmer.request(name)
        assert warmer.wait_idle(timeout=WAIT)
    finally:
        warmer.stop()


class Recorder:
    """A ``warm`` that records each scene it is asked for."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str | None]] = []

    def __call__(self, workspace: Workspace, name: str, template: str, colour: str | None) -> None:
        self.calls.append((name, template, colour))


def _scenes(*scenes: Scene):
    return lambda workspace, name: list(scenes)


def test_every_gallery_scene_is_cached_as_its_preview_composes_it(
    workspace_root: Path, workspace: Workspace
) -> None:
    edit_listing(
        workspace_root,
        media=[
            {"template": "flat-lay-01", "colour": "black"},
            "common-media/size-chart.png",
            {"template": "flat-lay-01", "colour": "ivory"},
        ],
    )

    _warmed(SceneWarmer(workspace), FIXTURE_LISTING)

    assert _cached(workspace) == {
        expected_scene(workspace_root, "flat-lay-01", colour, {colour: DESIGN})
        for colour in ("black", "ivory")
    }


def test_a_listing_that_does_not_load_warms_nothing(workspace: Workspace) -> None:
    _warmed(SceneWarmer(workspace), "no-such-listing")

    assert _cached(workspace) == set()


def test_a_scene_that_cannot_compose_is_skipped(workspace: Workspace) -> None:
    def warm(workspace: Workspace, name: str, template: str, colour: str | None) -> None:
        if template == "gone":
            raise TemplateMissing(template)
        recorder(workspace, name, template, colour)

    recorder = Recorder()
    warmer = SceneWarmer(
        workspace, scenes=_scenes(("gone", None), ("flat-lay-01", "moss")), warm=warm
    )

    _warmed(warmer, FIXTURE_LISTING)

    assert recorder.calls == [(FIXTURE_LISTING, "flat-lay-01", "moss")]


def test_a_bug_is_logged_and_the_next_listing_still_warms(
    workspace: Workspace, caplog: pytest.LogCaptureFixture
) -> None:
    recorder = Recorder()

    def warm(workspace: Workspace, name: str, template: str, colour: str | None) -> None:
        if name == "broken":
            raise RuntimeError("a bug")
        recorder(workspace, name, template, colour)

    warmer = SceneWarmer(workspace, scenes=_scenes(("flat-lay-01", "moss")), warm=warm)

    with caplog.at_level(logging.ERROR):
        _warmed(warmer, "broken", FIXTURE_LISTING)

    assert recorder.calls == [(FIXTURE_LISTING, "flat-lay-01", "moss")]
    assert "'broken'" in caplog.text


def test_a_listing_saved_again_mid_warm_starts_over_from_its_new_state(
    workspace: Workspace,
) -> None:
    """The first pass stops after the scene in hand; the second reads the
    listing again and warms all of it."""
    recorder = Recorder()
    entered, release = threading.Event(), threading.Event()

    def warm(workspace: Workspace, name: str, template: str, colour: str | None) -> None:
        recorder(workspace, name, template, colour)
        if len(recorder.calls) == 1:
            entered.set()
            assert release.wait(WAIT)

    warmer = SceneWarmer(
        workspace, scenes=_scenes(("flat-lay-01", "black"), ("flat-lay-01", "ivory")), warm=warm
    )
    warmer.start()
    try:
        warmer.request(FIXTURE_LISTING)
        assert entered.wait(WAIT)
        warmer.request(FIXTURE_LISTING)
        release.set()
        assert warmer.wait_idle(timeout=WAIT)
    finally:
        warmer.stop()

    assert recorder.calls == [
        (FIXTURE_LISTING, "flat-lay-01", "black"),
        (FIXTURE_LISTING, "flat-lay-01", "black"),
        (FIXTURE_LISTING, "flat-lay-01", "ivory"),
    ]


def test_a_listing_requested_twice_while_queued_is_warmed_once(workspace: Workspace) -> None:
    recorder = Recorder()
    warmer = SceneWarmer(workspace, scenes=_scenes(("flat-lay-01", "moss")), warm=recorder)

    warmer.request(FIXTURE_LISTING)
    warmer.request(FIXTURE_LISTING)
    _warmed(warmer)

    assert recorder.calls == [(FIXTURE_LISTING, "flat-lay-01", "moss")]


def test_a_stopped_warmer_takes_no_more_requests(workspace: Workspace) -> None:
    recorder = Recorder()
    warmer = SceneWarmer(workspace, scenes=_scenes(("flat-lay-01", "moss")), warm=recorder)
    warmer.start()
    warmer.stop()

    warmer.request(FIXTURE_LISTING)

    assert warmer.wait_idle(timeout=WAIT)
    assert recorder.calls == []

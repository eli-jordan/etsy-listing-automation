"""`WorkspaceFacts`: the workspace as a listing check sees it.

One subject -- what the module answers, and that it only reads each file once.
Whether the *endpoints* gather one per request is a behaviour question and
lives with them (`tests/behaviour/test_listings_api.py`).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings.workspace.facts import WorkspaceFacts
from etsy_listings.workspace.workspace import Workspace

from tests.support.builders import garment_profile_file

FIXTURE_PROFILE = "comfort-colors-1717"


def _break_profile(workspace_root: Path) -> None:
    """Valid YAML, invalid garment profile -- `ConfigLoadError`, which is what
    a profile file is expected to fail with. (Malformed *YAML* still escapes as
    a bare `yaml.ParserError`; that hole predates this module and is the
    workspace loaders' to close.)"""
    garment_profile_file(workspace_root, FIXTURE_PROFILE).write_text(
        "not-a-garment-profile: true\n", encoding="utf-8"
    )


@pytest.fixture
def facts(workspace_root: Path) -> WorkspaceFacts:
    return WorkspaceFacts.gather(Workspace.discover(root_override=workspace_root))


class TestGarmentProfiles:
    def test_a_real_profile_loads(self, facts: WorkspaceFacts) -> None:
        profile = facts.garment_profile(FIXTURE_PROFILE)
        assert profile is not None
        assert profile.sizes

    def test_it_is_read_once_however_often_it_is_asked_for(
        self, workspace_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The reason this module exists. `_describe` asked twice -- once for
        the issues, once for the resolved prices -- and got two reads."""
        workspace = Workspace.discover(root_override=workspace_root)
        loaded: list[str] = []
        real = Workspace.load_garment_profile

        def counting(self: Workspace, garment_profile: str) -> object:
            loaded.append(garment_profile)
            return real(self, garment_profile)

        monkeypatch.setattr(Workspace, "load_garment_profile", counting)
        facts = WorkspaceFacts.gather(workspace)

        for _ in range(3):
            assert facts.garment_profile(FIXTURE_PROFILE) is not None

        assert loaded == [FIXTURE_PROFILE]

    def test_gathering_reads_no_garment_profile_at_all(
        self, workspace_root: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Deliberately lazy: a workspace may hold many profiles and a request
        usually wants one. The template catalogue is the opposite -- every
        check needs all of it -- so that one is read in `gather`."""
        loaded: list[str] = []
        monkeypatch.setattr(
            Workspace, "load_garment_profile", lambda self, name: loaded.append(name)
        )
        WorkspaceFacts.gather(Workspace.discover(root_override=workspace_root))
        assert loaded == []

    def test_an_unchosen_name_answers_none_rather_than_raising(self, facts: WorkspaceFacts) -> None:
        """`""` is what a listing carries before the Variants dropdown is
        touched. It reaches `_segment`, which raises -- and a raise here would
        take the whole editor down over an ordinary unfinished listing."""
        assert facts.garment_profile("") is None

    def test_a_profile_that_will_not_validate_answers_none(self, workspace_root: Path) -> None:
        _break_profile(workspace_root)
        facts = WorkspaceFacts.gather(Workspace.discover(root_override=workspace_root))
        assert facts.garment_profile(FIXTURE_PROFILE) is None

    def test_a_profile_that_will_not_validate_is_still_a_name_that_exists(
        self, workspace_root: Path
    ) -> None:
        """Two different facts, and the checks read different ones: the
        existence check reads the names, the profile-dependent checks read
        :meth:`garment_profile`. A broken file is listed and will not load."""
        _break_profile(workspace_root)
        facts = WorkspaceFacts.gather(Workspace.discover(root_override=workspace_root))
        assert FIXTURE_PROFILE in facts.garment_profile_names


class TestTemplates:
    def test_a_colour_matrix_template_reports_its_photos_colours(
        self, facts: WorkspaceFacts
    ) -> None:
        colour_matrix = [
            (name, info) for name, info in facts.templates.items() if info.kind == "colour-matrix"
        ]
        assert colour_matrix, "the fixture workspace has a calibrated colour-matrix template"
        for _, info in colour_matrix:
            assert info.colours

    def test_an_uncalibrated_template_is_skipped_rather_than_guessed_at(
        self, workspace_root: Path
    ) -> None:
        """It has no kind to compare a media entry against. Same treatment as a
        template renamed out from under a listing."""
        workspace = Workspace.discover(root_override=workspace_root)
        uncalibrated = workspace.template_dir("uncalibrated-one")
        uncalibrated.mkdir(parents=True, exist_ok=True)
        (uncalibrated / "scene.png").write_bytes(b"")

        facts = WorkspaceFacts.gather(workspace)

        assert "uncalibrated-one" not in facts.templates
        assert facts.templates, "the calibrated ones are still there"

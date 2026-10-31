"""The Admin page's Settings operations, called directly against real files.

Admin plan, PR 4: ``settings.yaml`` reads with a revision of its own, apart
from ``shop.yaml``'s; revision-checked edits of ``batch_ai.concurrency`` and
``market_seo.weights`` validated as a whole ``Settings`` document; a missing
file that keeps the defaults until the first save creates it; and a file
that does not load refused, naming the file and the dotted key, never
repaired or replaced by defaults.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings.core.application import workspace_settings
from etsy_listings.core.application.refusals import (
    InvalidSettingsEdit,
    SettingsRevisionConflict,
)
from etsy_listings.core.config.errors import ConfigLoadError
from etsy_listings.core.workspace import layout
from etsy_listings.core.workspace.revisions import content_revision
from etsy_listings.core.workspace.workspace import Workspace

SETTINGS_YAML = """\
# Tuned after the October research run.
market_seo:
  weights:
    reviews: 0.3   # relative, as the spec allows
    favourites_per_day: 0.35
    search_rank: 0.2
    views_per_day: 0.1
    shop_sales: 0.05
    shop_rating: 0
batch_ai:
  concurrency: 2  # two at once is the CLI plan's limit
"""

PERCENTAGES = {
    "reviews": 30,
    "favourites_per_day": 35,
    "search_rank": 20,
    "views_per_day": 10,
    "shop_sales": 5,
    "shop_rating": 0,
}

DEFAULTS = {
    "reviews": 30,
    "favourites_per_day": 30,
    "search_rank": 20,
    "views_per_day": 10,
    "shop_sales": 5,
    "shop_rating": 5,
}


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    return Workspace.discover(root_override=workspace_root)


def settings_path(workspace: Workspace) -> Path:
    return workspace.root / layout.SETTINGS_FILE


def written(workspace: Workspace, text: str) -> Workspace:
    settings_path(workspace).write_bytes(text.replace("\n", "\r\n").encode())
    return workspace


# ------------------------------------------------------------------ reading


def test_a_missing_file_reads_as_the_defaults_and_creates_nothing(workspace: Workspace) -> None:
    assert not settings_path(workspace).exists()

    view = workspace_settings.read_settings(workspace)

    assert view.settings.batch_ai.concurrency == 1
    assert view.settings.market_seo.weights.model_dump() == DEFAULTS
    assert not settings_path(workspace).exists()


def test_a_read_carries_the_revision_of_the_file_s_exact_bytes(workspace: Workspace) -> None:
    written(workspace, SETTINGS_YAML)

    view = workspace_settings.read_settings(workspace)

    assert view.revision == content_revision(settings_path(workspace).read_bytes())
    assert view.settings.batch_ai.concurrency == 2
    assert view.settings.market_seo.weights.of("favourites_per_day") == 0.35


def test_the_settings_revision_is_its_own_not_shop_yaml_s(workspace: Workspace) -> None:
    written(workspace, SETTINGS_YAML)
    before = workspace_settings.read_settings(workspace).revision

    (workspace.root / layout.SHOP_FILE).write_bytes(
        (workspace.root / layout.SHOP_FILE).read_bytes() + b"# a shop note\n"
    )

    assert workspace_settings.read_settings(workspace).revision == before


@pytest.mark.parametrize(
    ("text", "key"),
    [
        ("batch_ai:\n  concurency: 2\n", "batch_ai.concurency"),
        ("market_seo:\n  weights:\n    review: 30\n", "market_seo.weights.review"),
        ("batch_ai:\n  concurrency: 9\n", "batch_ai.concurrency"),
        ("ai:\n  providers: []\n", "ai.providers"),
    ],
    ids=["misspelt-key", "unknown-metric", "too-high", "empty-chain"],
)
def test_a_file_that_does_not_load_is_refused_naming_file_and_key(
    workspace: Workspace, text: str, key: str
) -> None:
    written(workspace, text)
    before = settings_path(workspace).read_bytes()

    with pytest.raises(ConfigLoadError) as caught:
        workspace_settings.read_settings(workspace)

    assert caught.value.path == settings_path(workspace)
    assert f"{key}:" in str(caught.value)
    assert settings_path(workspace).read_bytes() == before, "never repaired"


# ------------------------------------------------------------------ editing


def test_the_first_save_creates_the_file_with_only_the_edited_key(workspace: Workspace) -> None:
    view = workspace_settings.read_settings(workspace)

    saved = workspace_settings.edit_settings(
        workspace, expected_revision=view.revision, changes={"batch_ai.concurrency": 3}
    )

    assert settings_path(workspace).read_text(encoding="utf-8") == "batch_ai:\n  concurrency: 3\n"
    assert saved.revision == content_revision(settings_path(workspace).read_bytes())
    assert saved.settings.batch_ai.concurrency == 3
    assert workspace.load_settings().batch_ai.concurrency == 3


def test_a_save_changes_only_its_value_and_keeps_every_other_byte(
    workspace: Workspace,
) -> None:
    written(workspace, SETTINGS_YAML)
    view = workspace_settings.read_settings(workspace)

    workspace_settings.edit_settings(
        workspace, expected_revision=view.revision, changes={"batch_ai.concurrency": 5}
    )

    expected = SETTINGS_YAML.replace("concurrency: 2", "concurrency: 5").replace("\n", "\r\n")
    assert settings_path(workspace).read_bytes() == expected.encode()


def test_saved_weights_are_the_page_s_whole_percentages(workspace: Workspace) -> None:
    written(workspace, SETTINGS_YAML)
    view = workspace_settings.read_settings(workspace)
    edited = PERCENTAGES | {"favourites_per_day": 30, "shop_rating": 5}

    saved = workspace_settings.edit_settings(
        workspace, expected_revision=view.revision, changes={"market_seo.weights": edited}
    )

    assert saved.settings.market_seo.weights.model_dump() == edited
    text = settings_path(workspace).read_bytes().decode()
    assert text.startswith("# Tuned after the October research run.\r\n")
    assert "    reviews: 30   # relative, as the spec allows\r\n" in text
    assert "  concurrency: 2  # two at once is the CLI plan's limit\r\n" in text


def test_reading_relative_weights_writes_nothing(workspace: Workspace) -> None:
    """Normalising them to percentages is the page's display; the file keeps
    its relative values until the seller edits a share."""
    written(workspace, SETTINGS_YAML)
    before = settings_path(workspace).read_bytes()

    workspace_settings.read_settings(workspace)

    assert settings_path(workspace).read_bytes() == before


def test_a_save_that_changes_nothing_leaves_the_file_byte_identical(
    workspace: Workspace,
) -> None:
    written(workspace, SETTINGS_YAML)
    view = workspace_settings.read_settings(workspace)
    mtime = settings_path(workspace).stat().st_mtime_ns

    saved = workspace_settings.edit_settings(
        workspace, expected_revision=view.revision, changes={"batch_ai.concurrency": 2}
    )

    assert saved.revision == view.revision
    assert settings_path(workspace).stat().st_mtime_ns == mtime


def test_an_explicit_default_on_a_missing_file_is_written(workspace: Workspace) -> None:
    view = workspace_settings.read_settings(workspace)

    workspace_settings.edit_settings(
        workspace, expected_revision=view.revision, changes={"batch_ai.concurrency": 1}
    )

    # One is the default, but writing it is still a change the seller made:
    # the file now says so, rather than relying on the default.
    assert settings_path(workspace).read_text(encoding="utf-8") == "batch_ai:\n  concurrency: 1\n"


def test_reset_writes_the_model_s_defaults(workspace: Workspace) -> None:
    written(workspace, SETTINGS_YAML)
    view = workspace_settings.read_settings(workspace)

    saved = workspace_settings.edit_settings(
        workspace,
        expected_revision=view.revision,
        changes={"market_seo.weights": workspace_settings.default_weights()},
    )

    assert workspace_settings.default_weights() == DEFAULTS
    assert saved.settings.market_seo.weights.model_dump() == DEFAULTS
    assert saved.settings.batch_ai.concurrency == 2, "reset touches only the weights"


# ----------------------------------------------------------------- refusals


def test_a_stale_revision_is_a_conflict_that_keeps_the_external_edit(
    workspace: Workspace,
) -> None:
    written(workspace, SETTINGS_YAML)
    view = workspace_settings.read_settings(workspace)
    edited = SETTINGS_YAML + "# a comment the seller added meanwhile\n"
    written(workspace, edited)

    with pytest.raises(SettingsRevisionConflict):
        workspace_settings.edit_settings(
            workspace, expected_revision=view.revision, changes={"batch_ai.concurrency": 4}
        )

    assert settings_path(workspace).read_bytes() == edited.replace("\n", "\r\n").encode()


def test_a_file_created_since_the_missing_read_is_a_conflict(workspace: Workspace) -> None:
    view = workspace_settings.read_settings(workspace)
    settings_path(workspace).write_text("batch_ai:\n  concurrency: 6\n", encoding="utf-8")

    with pytest.raises(SettingsRevisionConflict):
        workspace_settings.edit_settings(
            workspace, expected_revision=view.revision, changes={"batch_ai.concurrency": 2}
        )

    assert workspace.load_settings().batch_ai.concurrency == 6


@pytest.mark.parametrize(
    ("changes", "key"),
    [
        ({"batch_ai.concurrency": 0}, "batch_ai.concurrency"),
        ({"batch_ai.concurrency": 9}, "batch_ai.concurrency"),
        ({"batch_ai.concurrency": 2.5}, "batch_ai.concurrency"),
        ({"market_seo.weights": PERCENTAGES | {"rating": 0}}, "market_seo.weights"),
        (
            {"market_seo.weights": PERCENTAGES | {"reviews": -5, "shop_sales": 40}},
            "market_seo.weights.reviews",
        ),
        ({"market_seo.weights": dict.fromkeys(DEFAULTS, 0)}, "market_seo.weights"),
        ({"market_seo.weights": PERCENTAGES | {"reviews": 31}}, "market_seo.weights"),
        (
            {"market_seo.weights": PERCENTAGES | {"reviews": 29.5, "shop_sales": 5.5}},
            "market_seo.weights",
        ),
        ({"market_seo.weights": {"reviews": 100}}, "market_seo.weights"),
        ({"ai.providers": []}, "ai.providers"),
    ],
    ids=[
        "concurrency-zero",
        "concurrency-nine",
        "concurrency-fractional",
        "unknown-metric",
        "negative-weight",
        "all-zero",
        "not-totalling-100",
        "fractional-percentages",
        "missing-metrics",
        "not-editable-here",
    ],
)
def test_an_invalid_edit_names_its_key_and_writes_nothing(
    workspace: Workspace, changes: dict[str, object], key: str
) -> None:
    written(workspace, SETTINGS_YAML)
    view = workspace_settings.read_settings(workspace)
    before = settings_path(workspace).read_bytes()

    with pytest.raises(InvalidSettingsEdit) as caught:
        workspace_settings.edit_settings(
            workspace, expected_revision=view.revision, changes=changes
        )

    assert key in caught.value.field_errors
    assert settings_path(workspace).read_bytes() == before


@pytest.mark.parametrize(
    "source",
    ["batch_ai:\n  concurency: 2\n", "batch_ai: broken\n", "batch_ai:\n  concurrency: 0\n"],
)
def test_an_edit_to_a_file_that_does_not_load_is_refused(workspace: Workspace, source: str) -> None:
    """Saving a valid value must not paper over a hand edit that broke
    another key: the page shows the load error instead."""
    written(workspace, source)
    before = settings_path(workspace).read_bytes()
    revision = content_revision(settings_path(workspace).read_bytes())

    with pytest.raises(InvalidSettingsEdit) as caught:
        workspace_settings.edit_settings(
            workspace, expected_revision=revision, changes={"batch_ai.concurrency": 3}
        )

    assert any(key.startswith("batch_ai") for key in caught.value.field_errors)
    assert settings_path(workspace).read_bytes() == before


def test_provider_save_keeps_unrelated_source_and_refuses_last_disabled(
    workspace: Workspace,
) -> None:
    written(workspace, SETTINGS_YAML)
    view = workspace_settings.read_settings(workspace)
    providers = [
        {"name": "grok", "model": "retired", "effort": "high"},
        {"name": "codex", "enabled": False},
    ]
    saved = workspace_settings.edit_settings(
        workspace, expected_revision=view.revision, changes={"ai.providers": providers}
    )
    assert (
        settings_path(workspace)
        .read_bytes()
        .startswith(SETTINGS_YAML.replace("\n", "\r\n").encode())
    )
    assert [(p.name, p.enabled) for p in saved.settings.ai.providers] == [
        ("grok", True),
        ("codex", False),
    ]
    before = settings_path(workspace).read_bytes()
    with pytest.raises(InvalidSettingsEdit, match="at least one"):
        workspace_settings.edit_settings(
            workspace,
            expected_revision=saved.revision,
            changes={"ai.providers": [{"name": "grok", "enabled": False}]},
        )
    assert settings_path(workspace).read_bytes() == before
    noop = workspace_settings.edit_settings(
        workspace, expected_revision=saved.revision, changes={"ai.providers": providers}
    )
    assert noop.revision == saved.revision


def test_reordering_providers_moves_their_comments_and_original_spelling(
    workspace: Workspace,
) -> None:
    source = (
        "# preferences\nai:\n  providers:\n"
        '    - name: codex # first choice\n      model: "sol"\n'
        "    - name: claude # fallback\n      effort: high\n"
        "batch_ai: {concurrency: 2} # keep this\n"
    )
    written(workspace, source)
    view = workspace_settings.read_settings(workspace)
    workspace_settings.edit_settings(
        workspace,
        expected_revision=view.revision,
        changes={
            "ai.providers": [
                {"name": "claude", "effort": "high"},
                {"name": "codex", "model": "sol"},
            ]
        },
    )
    expected = (
        "# preferences\nai:\n  providers:\n"
        "    - name: claude # fallback\n      effort: high\n"
        '    - name: codex # first choice\n      model: "sol"\n'
        "batch_ai: {concurrency: 2} # keep this\n"
    )
    assert settings_path(workspace).read_bytes() == expected.replace("\n", "\r\n").encode()


def test_provider_reorder_does_not_materialize_untouched_optional_defaults(
    workspace: Workspace,
) -> None:
    source = "ai:\n  providers:\n    - name: codex # account defaults\n    - name: claude\n"
    written(workspace, source)
    view = workspace_settings.read_settings(workspace)
    rows = [p.model_dump() for p in reversed(view.settings.ai.providers)]
    workspace_settings.edit_settings(
        workspace, expected_revision=view.revision, changes={"ai.providers": rows}
    )
    assert settings_path(workspace).read_bytes() == (
        b"ai:\r\n  providers:\r\n    - name: claude\r\n    - name: codex # account defaults\r\n"
    )

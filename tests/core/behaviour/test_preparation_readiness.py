"""``template_readiness``: one answer to "can this saved template render?"
for any renderer, with typed causes."""

from __future__ import annotations

import json

from etsy_listings.core.preparation.readiness import catalog_readiness, template_readiness
from etsy_listings.core.workspace import Workspace

from tests.support.marigold import listing_with_marigold, marigold_template


def test_photo_warp_needs_no_preparation_and_reads_no_maps(workspace_root) -> None:
    workspace = Workspace.discover(root_override=workspace_root)
    config = workspace.load_template_config("flat-lay-01")
    # The catalogue knows without validation, so the full question reads nothing either.
    workspace.template_maps_dir("flat-lay-01").mkdir(parents=True)
    workspace.template_map_current("flat-lay-01").write_text("not a pointer")

    assert catalog_readiness(config) is not None
    readiness = template_readiness(workspace, "flat-lay-01", config)

    assert readiness.state == "not_required"
    assert readiness.can_render


def test_marigold_must_be_validated_and_reports_missing_maps(workspace_root) -> None:
    workspace = marigold_template(workspace_root)
    config = workspace.load_template_config("shirt")

    assert catalog_readiness(config) is None
    readiness = template_readiness(workspace, "shirt", config)

    assert (readiness.state, readiness.reason) == ("needs_preparation", "missing_maps")
    assert not readiness.can_render


def test_a_prepared_marigold_template_is_ready(workspace_root) -> None:
    workspace, _ = listing_with_marigold(workspace_root, prepare=True)

    readiness = template_readiness(workspace, "shirt", workspace.load_template_config("shirt"))

    assert readiness.state == "ready"
    assert readiness.content_digest is not None


def test_an_unreadable_schema_is_reported_by_type_not_message(workspace_root) -> None:
    workspace, _ = listing_with_marigold(workspace_root, prepare=True)
    pointer = workspace.template_map_current("shirt")
    pointer.write_text(json.dumps({**json.loads(pointer.read_text()), "schema_version": 99}))

    readiness = template_readiness(workspace, "shirt", workspace.load_template_config("shirt"))

    assert (readiness.state, readiness.reason) == ("out_of_date", "unsupported_schema")

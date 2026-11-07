"""One template that does not load stays that template's problem.

Listing templates is how a seller reaches the UI that repairs one, so a
damaged calibration transaction or a ``template.yaml`` that will not parse must
say so on its own row and leave every other template alone. A stage reading it
refuses rather than raises (ADR-0053).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings.core.application.mockup_templates import (
    TemplateOverview,
    assign_kind,
    list_templates,
    read_config,
)
from etsy_listings.core.engine.stage import Blocked
from etsy_listings.core.engine.stages.render import RenderStage
from etsy_listings.core.errors import ConflictError
from etsy_listings.core.workspace import WorkspaceFacts
from etsy_listings.core.workspace.workspace import Workspace

from tests.support.builders import FIXTURE_LISTING, a_context

DAMAGED = "flat-lay-01"
HEALTHY = "colour-chart-01"


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    return Workspace.discover(root_override=workspace_root)


def _damage_transaction(workspace: Workspace, name: str) -> None:
    """What a save interrupted on a failing disk leaves: recovery data that
    cannot be trusted, so nothing may roll it forward."""
    transaction = workspace.template_calibration_transaction(name)
    transaction.mkdir(parents=True)
    (transaction / "manifest.json").write_bytes(b"corrupted")


def _rows(workspace: Workspace) -> dict[str, TemplateOverview]:
    return {row.name: row for row in list_templates(workspace)}


def test_a_damaged_transaction_is_one_row_saying_it_needs_repair(workspace: Workspace) -> None:
    _damage_transaction(workspace, DAMAGED)

    rows = _rows(workspace)

    assert "repair" in (rows[DAMAGED].status_reason or "")
    assert not rows[DAMAGED].calibrated
    assert rows[HEALTHY].calibrated


def test_gathering_facts_leaves_out_only_the_damaged_template(workspace: Workspace) -> None:
    _damage_transaction(workspace, DAMAGED)

    templates = WorkspaceFacts.gather(workspace).templates

    assert DAMAGED not in templates
    assert HEALTHY in templates


def test_the_render_stage_refuses_a_template_needing_repair(workspace_root: Path) -> None:
    ctx = a_context(workspace_root)
    _damage_transaction(ctx.workspace, DAMAGED)

    desired = RenderStage().desired(ctx, FIXTURE_LISTING, None)

    assert isinstance(desired, Blocked)
    assert "transaction" in desired.message


class TestATemplateFileThatWillNotParse:
    @pytest.fixture(autouse=True)
    def _broken(self, workspace: Workspace) -> None:
        workspace.template_config_file(DAMAGED).write_text("kind: [unclosed", encoding="utf-8")

    def test_it_is_not_listed_as_never_having_had_a_kind(self, workspace: Workspace) -> None:
        rows = _rows(workspace)

        assert rows[DAMAGED].has_config
        assert "not valid YAML" in (rows[DAMAGED].status_reason or "")
        assert rows[HEALTHY].calibrated

    def test_reading_it_says_why_rather_than_that_it_is_missing(self, workspace: Workspace) -> None:
        with pytest.raises(ConflictError, match="not valid YAML"):
            read_config(workspace, DAMAGED)

    def test_assigning_a_kind_refuses_with_the_same_reason(self, workspace: Workspace) -> None:
        with pytest.raises(ConflictError, match="not valid YAML"):
            assign_kind(workspace, DAMAGED, "single")

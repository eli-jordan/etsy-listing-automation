"""Admin > Settings > Template rendering over HTTP (template positions PR 5).

The limits save through the settings PATCH like every other key: validated as
a whole ``Settings``, revision-checked, and written as splices that keep the
seller's source (ADR-0055). The impact read answers the confirmation's
question before anything is written: which saved positions the candidate
limits would block, and which Marigold templates would need inference.
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from etsy_listings.core.render.positions import Pose, compose
from etsy_listings.core.workspace.workspace import Workspace
from etsy_listings.server.api.app import create_app

from tests.support.builders import FIXTURE_LISTING, edit_listing

TEMPLATE = "flat-lay-01"
SETTINGS = "/api/admin/settings"
IMPACT = "/api/admin/settings/template-positions/impact"
DEFAULTS = {"scale": {"min": 0.8, "max": 1.1}, "offset": 0.1, "rotation": 15}


@pytest.fixture
def workspace(workspace_root: Path) -> Workspace:
    return Workspace.discover(root_override=workspace_root)


@pytest.fixture
def client(workspace: Workspace) -> TestClient:
    return TestClient(create_app(workspace))


def limits(*, smallest=0.8, largest=1.1, offset=0.1, rotation=15) -> dict[str, object]:
    return {"scale": {"min": smallest, "max": largest}, "offset": offset, "rotation": rotation}


def position_listing(workspace: Workspace, pose: Pose) -> None:
    box = compose(workspace.load_template_config(TEMPLATE).bounding_box, pose)
    edit_listing(
        workspace.root,
        template_positions={TEMPLATE: {"bounding_box": [point.model_dump() for point in box]}},
    )


def save(client: TestClient, positions: dict[str, object]):
    revision = client.get(SETTINGS).json()["revision"]
    return client.patch(
        SETTINGS, json={"revision": revision, "changes": {"template_positions": positions}}
    )


def test_saving_limits_writes_only_the_changed_leaf_and_keeps_the_source(
    client: TestClient, workspace: Workspace
) -> None:
    path = workspace.settings_file()
    source = (
        b"# tuned by hand\r\ntemplate_positions:\r\n"
        b"  scale: {min: 0.80, max: 1.10}  # keep\r\n  rotation: 15\r\n"
    )
    path.write_bytes(source)

    saved = save(client, limits(largest=1.2))

    assert saved.status_code == 200
    assert saved.json()["template_positions"] == limits(largest=1.2)
    assert path.read_bytes() == source.replace(b"max: 1.10", b"max: 1.2")
    assert client.get(SETTINGS).json() == saved.json()


def test_first_save_writes_only_what_differs_from_the_defaults(
    client: TestClient, workspace: Workspace
) -> None:
    saved = save(client, limits(offset=0.15))

    assert saved.status_code == 200
    assert workspace.settings_file().read_text() == "template_positions:\n  offset: 0.15\n"


def test_unchanged_limits_leave_the_file_untouched(
    client: TestClient, workspace: Workspace
) -> None:
    path = workspace.settings_file()
    path.write_bytes(b"template_positions:\n  offset: 0.10\n")
    before = path.read_bytes()

    assert save(client, DEFAULTS).status_code == 200
    assert path.read_bytes() == before


@pytest.mark.parametrize(
    ("positions", "key"),
    [
        (limits(smallest=1.05), "template_positions.scale.min"),
        (limits(largest=1.6), "template_positions.scale.max"),
        (limits(offset=0.3), "template_positions.offset"),
        (limits(rotation=-1), "template_positions.rotation"),
        ({**DEFAULTS, "skew": 2}, "template_positions.skew"),
    ],
)
def test_out_of_range_limits_are_refused_naming_the_key(
    client: TestClient, workspace: Workspace, positions: dict[str, object], key: str
) -> None:
    refused = save(client, positions)

    assert refused.status_code == 422
    assert key in refused.json()["field_errors"]
    assert not workspace.settings_file().exists()


def test_a_stale_revision_conflicts_and_writes_nothing(
    client: TestClient, workspace: Workspace
) -> None:
    revision = client.get(SETTINGS).json()["revision"]
    workspace.settings_file().write_bytes(b"batch_ai:\n  concurrency: 2\n")

    conflict = client.patch(
        SETTINGS, json={"revision": revision, "changes": {"template_positions": DEFAULTS}}
    )

    assert conflict.status_code == 412
    assert workspace.settings_file().read_bytes() == b"batch_ai:\n  concurrency: 2\n"


def test_impact_names_listings_the_candidate_limits_would_block(
    client: TestClient, workspace: Workspace
) -> None:
    position_listing(workspace, Pose(scale=1.08, rotation=12))

    assert client.post(IMPACT, json={"limits": DEFAULTS}).json() == {
        "outside": [],
        "templates_needing_inference": [],
    }
    narrowed = client.post(IMPACT, json={"limits": limits(largest=1.05, rotation=10)})

    assert narrowed.status_code == 200
    assert narrowed.json() == {
        "outside": [{"listing": FIXTURE_LISTING, "positions": [f"template_positions.{TEMPLATE}"]}],
        "templates_needing_inference": [],
    }
    assert not workspace.settings_file().exists()


def test_impact_ignores_problems_the_limits_do_not_cause(
    client: TestClient, workspace: Workspace
) -> None:
    """A position the listing must fix anyway (here: a template no longer in
    ``media``) is not something new limits would block."""
    position_listing(workspace, Pose(scale=1.08))
    edit_listing(workspace.root, media=[])

    impact = client.post(IMPACT, json={"limits": limits(largest=1.0)})

    assert impact.json()["outside"] == []


def test_impact_refuses_limits_the_save_would_refuse(client: TestClient) -> None:
    refused = client.post(IMPACT, json={"limits": limits(smallest=1.2)})

    assert refused.status_code == 422


def test_impact_names_the_placement_of_a_multiple_template(
    client: TestClient, workspace: Workspace
) -> None:
    chart = workspace.load_template_config("colour-chart-01")
    boxes = {placement.id: placement.bounding_box for placement in chart.placements}
    edit_listing(
        workspace.root,
        media=[{"template": "colour-chart-01"}],
        template_positions={
            "colour-chart-01": {
                "placements": {
                    pid: {
                        "bounding_box": [
                            point.model_dump() for point in compose(box, Pose(rotation=rotation))
                        ]
                    }
                    for (pid, box), rotation in zip(boxes.items(), (5, 14), strict=True)
                }
            }
        },
    )

    impact = client.post(IMPACT, json={"limits": limits(rotation=10)})

    assert impact.json()["outside"] == [
        {
            "listing": FIXTURE_LISTING,
            "positions": ["template_positions.colour-chart-01.placements.fixture-placement-2"],
        }
    ]

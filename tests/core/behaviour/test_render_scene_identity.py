"""The render stage's hashed identity for real workspace scenes, pinned to the
values ``main`` produced before the scene renderer became a tagged variant.

``recipe()`` is written into every lockfile's ``scene_config`` and feeds
``input_hash``; a byte of drift here makes every existing listing plan a
re-render. These literals are deliberately not recomputed: a change to them
is a change to every user's lockfile and has to be made on purpose.

Only values independent of checked-out text bytes are pinned here -- a
photo-warp ``scene_hash`` includes the ``template.yaml`` file hash, which a
CRLF checkout changes. ``tests/core/unit/test_scene_hash.py`` pins those
hashes over hand-built inputs instead.
"""

from etsy_listings.core.engine import Event
from etsy_listings.core.engine.stages.render import RenderStage, scene_hash

from tests.support.builders import FIXTURE_LISTING, a_context
from tests.support.marigold import listing_with_marigold

DESIGN_HASH = "sha256:9dabb904cf78846f6019f67624069a54cbaa7f5873fb93ecec02af656baf2894"
FLAT_LAY_CONFIG = (
    '{"bounding_box":[{"x":144.0,"y":126.72},{"x":345.59999999999997,"y":115.2},'
    '{"x":355.2,"y":391.68},{"x":134.4,"y":403.2}],'
    '"displace":{"enabled":false,"strength":0.0},'
    '"shade":{"blend":"soft-light","enabled":true,"opacity":0.6}}'
)


def test_photo_warp_recipe_is_unchanged(workspace_root):
    desired = RenderStage().desired(a_context(workspace_root), FIXTURE_LISTING, None)

    assert [work.recipe() for work in desired.works] == [
        {
            "template": "flat-lay-01",
            "kind": "colour-matrix",
            "layers": [
                {"colour": colour, "design_hash": DESIGN_HASH, "render_config": FLAT_LAY_CONFIG}
            ],
        }
        for colour in ["black", "blue-jean", "ivory", "moss"]
    ]


def test_marigold_recipe_scene_hash_and_input_hash_are_unchanged(workspace_root):
    listing_with_marigold(workspace_root, prepare=True)
    stage = RenderStage()
    desired = stage.desired(a_context(workspace_root), FIXTURE_LISTING, None)
    (work,) = desired.works

    assert work.recipe() == {
        "template": "shirt",
        "kind": "single",
        "renderer": "marigold",
        "map_content": "ec1b48c1891dbf04c1e52dccaab9a3b21316c072e05479e6afbe8c7a78c916e7",
        "appearance": {
            "lighting_source": "estimated",
            "lighting_strength": 1.0,
            "fabric_texture": 0.25,
            "print_shine": 0.0,
        },
        "layers": [{"placement_id": None, "design_hash": DESIGN_HASH, "colour": None}],
    }
    assert scene_hash(desired, work) == (
        "sha256:732995475346757e7806088a3fa6fe448761ceba8cae0f3dad5375213a388419"
    )
    assert stage.review_hash(desired) == (
        "sha256:4201b54bb11fcfc8b76e7ad96944359e14ce0a8b83aa743c8f8882b620176c37"
    )


def test_marigold_swatches_sample_the_template_geometry(workspace_root):
    """A prepared scene's swatch comes from its placement's bounding box over
    the photo, the same box Photo warp would have printed into."""
    listing_with_marigold(workspace_root, prepare=True)
    events: list[Event] = []
    ctx = a_context(workspace_root, on_event=events.append)
    stage = RenderStage()
    stage.apply(ctx, stage.desired(ctx, FIXTURE_LISTING, None))

    # The fixture fills the box with navy (tests/support/marigold.py).
    assert [(event.message, event.swatches) for event in events] == [
        ("rendered shirt", ((0, 0, 128),))
    ]

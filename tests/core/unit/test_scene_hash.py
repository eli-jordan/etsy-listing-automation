"""``scene_hash``: pure, so this builds a `RenderDesired` and a couple of
`SceneWork` values by hand rather than through a workspace and the render
stage's `desired()`. The one property worth pinning down is the reason it
exists at all -- a change to one scene's own inputs must not move another
scene's hash, which the aggregate `input_hash` (by design) does not promise."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from etsy_listings.core.engine.stages.render import (
    RenderDesired,
    ResolvedLayer,
    SceneWork,
    scene_hash,
)
from etsy_listings.core.render.config import Point, RenderConfig

SQUARE_BOX = (
    Point(x=0.0, y=0.0),
    Point(x=100.0, y=0.0),
    Point(x=100.0, y=100.0),
    Point(x=0.0, y=100.0),
)

CFG = RenderConfig(bounding_box=SQUARE_BOX)


def _work(
    *, template: str, colour: str | None, design_hash: str, cfg: RenderConfig = CFG
) -> SceneWork:
    key = f"{template}/{colour}" if colour is not None else template
    layer = ResolvedLayer(
        colour=colour, design=Path("designs/design.png"), design_hash=design_hash, cfg=cfg
    )
    return SceneWork(
        key=key,
        template=template,
        colour=colour,
        kind="colour-matrix" if colour is not None else "single",
        config_file=Path(f"mockup-templates/{template}/template.yaml"),
        base_image=Path(f"mockup-templates/{template}/{colour or 'scene'}.png"),
        map_key=colour or template,
        layers=(layer,),
        output=Path(f".cache/renders/listing/{template}/{colour or 'scene'}.png"),
    )


def _desired(works: tuple[SceneWork, ...], **hashes: dict[str, str]) -> RenderDesired:
    return RenderDesired(
        listing="listing",
        root=Path("/workspace"),
        works=works,
        template_hash=hashes["template_hash"],
        base_hash=hashes["base_hash"],
    )


def test_scene_hash_is_deterministic() -> None:
    work = _work(template="flat-lay-01", colour="black", design_hash="sha256:aaa")
    desired = _desired(
        (work,),
        template_hash={"flat-lay-01": "sha256:ttt"},
        base_hash={"flat-lay-01/black": "sha256:bbb"},
    )
    assert scene_hash(desired, work) == scene_hash(desired, work)


def test_scene_hash_is_independent_of_an_unrelated_scenes_photo() -> None:
    """Two colours of the same colour-matrix template share a `template_hash`
    entry but not a `base_hash` one -- replacing one colour's photo must not
    move the other colour's hash."""
    black = _work(template="flat-lay-01", colour="black", design_hash="sha256:aaa")
    moss = _work(template="flat-lay-01", colour="moss", design_hash="sha256:aaa")
    desired = _desired(
        (black, moss),
        template_hash={"flat-lay-01": "sha256:ttt"},
        base_hash={"flat-lay-01/black": "sha256:bbb-black", "flat-lay-01/moss": "sha256:bbb-moss"},
    )
    before_black = scene_hash(desired, black)

    changed = replace(desired, base_hash={**desired.base_hash, "flat-lay-01/moss": "sha256:new"})

    assert scene_hash(changed, black) == before_black
    assert scene_hash(changed, moss) != scene_hash(desired, moss)


def test_scene_hash_is_independent_of_an_unrelated_scenes_artwork() -> None:
    """Two scenes on different templates, each printing its own file --
    changing one's design must not move the other's hash."""
    front = _work(template="flat-lay-01", colour=None, design_hash="sha256:aaa")
    back = _work(template="colour-chart-01", colour=None, design_hash="sha256:bbb")
    desired = _desired(
        (front, back),
        template_hash={"flat-lay-01": "sha256:ttt-1", "colour-chart-01": "sha256:ttt-2"},
        base_hash={"flat-lay-01": "sha256:base-1", "colour-chart-01": "sha256:base-2"},
    )
    before_front = scene_hash(desired, front)

    new_back = replace(back, layers=(replace(back.layers[0], design_hash="sha256:new"),))
    changed = replace(desired, works=(front, new_back))

    assert scene_hash(changed, front) == before_front
    assert scene_hash(changed, new_back) != scene_hash(desired, back)


def test_scene_hash_is_independent_of_an_unrelated_templates_yaml() -> None:
    front = _work(template="flat-lay-01", colour=None, design_hash="sha256:aaa")
    back = _work(template="colour-chart-01", colour=None, design_hash="sha256:bbb")
    desired = _desired(
        (front, back),
        template_hash={"flat-lay-01": "sha256:ttt-1", "colour-chart-01": "sha256:ttt-2"},
        base_hash={"flat-lay-01": "sha256:base-1", "colour-chart-01": "sha256:base-2"},
    )
    before_front = scene_hash(desired, front)

    changed = replace(
        desired, template_hash={**desired.template_hash, "colour-chart-01": "sha256:new"}
    )

    assert scene_hash(changed, front) == before_front
    assert scene_hash(changed, back) != scene_hash(desired, back)


def test_scene_hash_changes_when_its_own_render_config_changes() -> None:
    work = _work(template="flat-lay-01", colour="black", design_hash="sha256:aaa")
    other_cfg_work = replace(
        work,
        layers=(
            replace(
                work.layers[0],
                cfg=RenderConfig(
                    bounding_box=SQUARE_BOX,
                    shade=work.layers[0].cfg.shade.model_copy(update={"opacity": 0.9}),
                ),
            ),
        ),
    )
    hashes = {
        "template_hash": {"flat-lay-01": "sha256:ttt"},
        "base_hash": {"flat-lay-01/black": "sha256:bbb"},
    }
    desired = _desired((work,), **hashes)
    changed_desired = _desired((other_cfg_work,), **hashes)

    assert scene_hash(desired, work) != scene_hash(changed_desired, other_cfg_work)

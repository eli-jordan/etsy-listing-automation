"""Prepared rendering through the listing engine, with durable synthetic maps."""

from etsy_listings.core.config.listing_validation import check_listing
from etsy_listings.core.engine import build_plan
from etsy_listings.core.engine.stages.render import RenderStage
from etsy_listings.core.preparation.artifacts import Artifacts
from etsy_listings.core.workspace import WorkspaceFacts
from etsy_listings.core.workspace.listing_documents import ListingDocuments

from tests.support.builders import FIXTURE_LISTING, a_context, a_lock
from tests.support.marigold import marigold_template, material_maps


def listing_with_marigold(workspace_root, *, prepare=False):
    workspace = marigold_template(workspace_root)
    ListingDocuments(workspace).edit(
        FIXTURE_LISTING, lambda document: {**document, "media": [{"template": "shirt"}]}
    )
    if prepare:
        artifacts = Artifacts(workspace)
        inputs = artifacts.saved_inputs("shirt", evidence={None: "a" * 64})
        artifacts.publish(
            "shirt", inputs, {None: material_maps((64, 64))}, current_inputs=lambda: inputs
        )
    return workspace, workspace.load_listing(FIXTURE_LISTING)


def test_missing_maps_have_the_same_listing_and_engine_refusal(workspace_root):
    workspace, listing = listing_with_marigold(workspace_root)
    facts = WorkspaceFacts.gather(workspace)
    issues = check_listing(
        listing,
        garment_profile=facts.garment_profile(listing.garment_profile),
        garment_profile_names=facts.garment_profile_names,
        design_paths={},
        templates=facts.templates,
    )
    planned = build_plan(a_context(workspace_root), FIXTURE_LISTING, a_lock(), (RenderStage(),))
    refusal = planned.plan.stage_plans[0].blocked
    assert refusal is not None
    assert "Prepare" in refusal
    assert refusal in [i.message for i in issues]


def test_prepared_listing_renders_and_repeat_apply_is_idle(workspace_root):
    from etsy_listings.core.engine import execute

    workspace, listing = listing_with_marigold(workspace_root, prepare=True)
    ctx = a_context(workspace_root)
    stage = RenderStage()
    planned = build_plan(ctx, FIXTURE_LISTING, a_lock(), (stage,))
    assert planned.plan.stage_plans[0].blocked is None
    first = execute(ctx, planned, a_lock())
    assert workspace.render_file(FIXTURE_LISTING, "shirt", None).is_file()
    again = build_plan(ctx, FIXTURE_LISTING, first, (stage,))
    assert not again.plan.stage_plans[0].will_run
    assert execute(ctx, again, first).input_hash() == first.input_hash()


def test_preview_is_promoted_only_while_actual_scene_identity_matches(workspace_root):
    import pytest
    from PIL import Image

    from etsy_listings.core.engine import StageBlockedError

    workspace, _ = listing_with_marigold(workspace_root, prepare=True)
    ctx = a_context(workspace_root)
    stage = RenderStage()
    desired = stage.desired(ctx, FIXTURE_LISTING, None)
    stage.preview(ctx, desired, None)
    design = desired.works[0].layers[0].design
    Image.new("RGBA", (64, 64), "red").save(design)
    with pytest.raises(StageBlockedError, match="changed"):
        stage.apply(ctx, desired)
    assert not workspace.render_file(FIXTURE_LISTING, "shirt", None).exists()


def test_matching_preview_promotes_exact_bytes_without_composition(workspace_root, monkeypatch):
    from etsy_listings.core.application.prepared_previews import prepared_preview
    from etsy_listings.core.engine.stages import render as render_module
    from etsy_listings.core.engine.stages.render import scene_hash
    from etsy_listings.core.render import encode_png

    workspace, _ = listing_with_marigold(workspace_root, prepare=True)
    ctx = a_context(workspace_root)
    stage = RenderStage()
    desired = stage.desired(ctx, FIXTURE_LISTING, None)
    work = desired.works[0]
    authoring = prepared_preview(
        workspace, "shirt", config=None, colour=None, design=lambda: work.layers[0].design
    )
    assert authoring.render_identity == scene_hash(desired, work)
    stage.preview(ctx, desired, None)
    target = workspace.preview_file(
        FIXTURE_LISTING, "shirt", None, authoring.render_identity.removeprefix("sha256:")
    )
    expected = target.read_bytes()
    assert expected == encode_png(authoring.image)

    def unexpected_render(*args, **kwargs):
        raise AssertionError("matching preview must be promoted")

    monkeypatch.setattr(render_module, "render_marigold_scene", unexpected_render)
    stage.apply(ctx, desired)
    assert workspace.render_file(FIXTURE_LISTING, "shirt", None).read_bytes() == expected


def test_stale_geometry_blocks_every_required_scene_with_shared_refusal(workspace_root):
    from etsy_listings.core.render import Point

    workspace, listing = listing_with_marigold(workspace_root, prepare=True)
    config = workspace.load_template_config("shirt")
    config = config.model_copy(
        update={"bounding_box": (Point(x=13, y=12), *config.bounding_box[1:])}
    )
    workspace.save_template_config("shirt", config)
    facts = WorkspaceFacts.gather(workspace)
    planned = build_plan(a_context(workspace_root), FIXTURE_LISTING, a_lock(), (RenderStage(),))
    refusal = planned.plan.stage_plans[0].blocked
    assert refusal == facts.templates["shirt"].preparation_error
    assert "out of date" in refusal


def test_compatible_map_republication_and_cache_deletion_keep_render_identity(workspace_root):
    from etsy_listings.core.engine import execute
    from etsy_listings.core.workspace.workspace import remove_tree

    workspace, _ = listing_with_marigold(workspace_root, prepare=True)
    ctx = a_context(workspace_root)
    stage = RenderStage()
    first = execute(ctx, build_plan(ctx, FIXTURE_LISTING, a_lock(), (stage,)), a_lock())
    artifacts = Artifacts(workspace)
    inputs = artifacts.saved_inputs("shirt")
    artifacts.publish(
        "shirt",
        inputs,
        {None: material_maps((64, 64))},
        current_inputs=lambda: inputs,
        provenance={"engine_version": "compatible-new", "timestamp": "tomorrow"},
    )
    again = build_plan(ctx, FIXTURE_LISTING, first, (stage,))
    assert not again.plan.stage_plans[0].will_run
    remove_tree(workspace.cache())
    restored = execute(ctx, build_plan(ctx, FIXTURE_LISTING, first, (stage,)), first)
    assert restored.applied["render"] == first.applied["render"]
    assert restored.outputs == first.outputs


def test_multiple_placements_resolve_actual_artwork_and_preserve_paint_order(workspace_root):
    from PIL import Image

    from etsy_listings.core.application.prepared_previews import prepared_preview
    from etsy_listings.core.engine import execute
    from etsy_listings.core.engine.stages.render import scene_hash
    from etsy_listings.core.render import (
        MaterialLayer,
        encode_png,
        load_design,
        load_template_base,
        render_marigold_scene,
    )

    workspace = marigold_template(workspace_root, "multiple")
    config = workspace.load_template_config("shirt")
    placements = [
        p.model_copy(update={"artwork": artwork})
        for p, artwork in zip(config.placements, ["red", "blue"], strict=True)
    ]
    workspace.save_template_config("shirt", config.model_copy(update={"placements": placements}))
    red = workspace.resolve("designs/red.png", workspace.root)
    blue = workspace.resolve("designs/blue.png", workspace.root)
    Image.new("RGBA", (16, 16), "red").save(red)
    Image.new("RGBA", (16, 16), "blue").save(blue)
    ListingDocuments(workspace).edit(
        FIXTURE_LISTING,
        lambda document: {
            **document,
            "design": {"red": "designs/red.png", "blue": "designs/blue.png"},
            "media": [{"template": "shirt"}],
        },
    )
    artifacts = Artifacts(workspace)
    inputs = artifacts.saved_inputs("shirt", evidence={p.id: "a" * 64 for p in placements})
    left = material_maps((64, 64))
    right = material_maps((64, 64))
    right.visibility[:, :32] = 0
    maps = {"left-shirt": left, "right-shirt": right}
    artifacts.publish("shirt", inputs, maps, current_inputs=lambda: inputs)
    ctx = a_context(workspace_root)
    stage = RenderStage()
    desired = stage.desired(ctx, FIXTURE_LISTING, None)
    work = desired.works[0]
    authoring = prepared_preview(workspace, "shirt", config=None, colour=None, design=lambda: red)
    assert scene_hash(desired, work) != authoring.render_identity
    first = execute(ctx, build_plan(ctx, FIXTURE_LISTING, a_lock(), (stage,)), a_lock())
    expected = render_marigold_scene(
        load_template_base(work.base_image),
        [
            MaterialLayer(load_design(red), left, "left-shirt"),
            MaterialLayer(load_design(blue), right, "right-shirt"),
        ],
        appearance=config.renderer.config.appearance,
    )
    assert workspace.render_file(FIXTURE_LISTING, "shirt", None).read_bytes() == encode_png(
        expected
    )
    workspace.save_template_config(
        "shirt", config.model_copy(update={"placements": placements[::-1]})
    )
    reversed_plan = build_plan(ctx, FIXTURE_LISTING, first, (stage,))
    assert reversed_plan.plan.stage_plans[0].will_run
    assert reversed_plan.plan.stage_plans[0].blocked is None


def test_changed_geometry_after_review_cannot_promote_a_previous_preview(workspace_root):
    import pytest

    from etsy_listings.core.engine import StageBlockedError
    from etsy_listings.core.render import Point

    workspace, _ = listing_with_marigold(workspace_root, prepare=True)
    ctx = a_context(workspace_root)
    stage = RenderStage()
    desired = stage.desired(ctx, FIXTURE_LISTING, None)
    stage.preview(ctx, desired, None)
    config = workspace.load_template_config("shirt")
    workspace.save_template_config(
        "shirt",
        config.model_copy(update={"bounding_box": (Point(x=13, y=12), *config.bounding_box[1:])}),
    )
    with pytest.raises(StageBlockedError, match="out of date"):
        stage.apply(ctx, desired)


def test_listing_preview_uses_the_same_missing_map_explanation(workspace_root):
    import pytest

    from etsy_listings.core.application.prepared_previews import prepared_preview
    from etsy_listings.core.render import PreparationRequired

    workspace, _ = listing_with_marigold(workspace_root)
    refusal = (
        build_plan(a_context(workspace_root), FIXTURE_LISTING, a_lock(), (RenderStage(),))
        .plan.stage_plans[0]
        .blocked
    )
    with pytest.raises(PreparationRequired) as error:
        prepared_preview(
            workspace,
            "shirt",
            config=None,
            colour=None,
            design=lambda: workspace.design_file("take-a-hike"),
        )
    assert str(error.value) == refusal


def test_numerical_map_content_and_appearance_change_render_identity(workspace_root):
    from etsy_listings.core.engine import execute
    from etsy_listings.core.engine.stages.render import scene_hash

    workspace, _ = listing_with_marigold(workspace_root, prepare=True)
    ctx = a_context(workspace_root)
    stage = RenderStage()
    original = stage.desired(ctx, FIXTURE_LISTING, None)
    lock = execute(ctx, build_plan(ctx, FIXTURE_LISTING, a_lock(), (stage,)), a_lock())
    artifacts = Artifacts(workspace)
    inputs = artifacts.saved_inputs("shirt")
    maps = material_maps((64, 64))
    maps.visibility[:, :32] = 0
    artifacts.publish("shirt", inputs, {None: maps}, current_inputs=lambda: inputs)
    changed = stage.desired(ctx, FIXTURE_LISTING, None)
    assert scene_hash(original, original.works[0]) != scene_hash(changed, changed.works[0])
    assert build_plan(ctx, FIXTURE_LISTING, lock, (stage,)).plan.stage_plans[0].will_run
    config = workspace.load_template_config("shirt")
    appearance = config.renderer.config.appearance.model_copy(update={"lighting_strength": 0.0})
    renderer = config.renderer.model_copy(
        update={"config": config.renderer.config.model_copy(update={"appearance": appearance})}
    )
    workspace.save_template_config("shirt", config.model_copy(update={"renderer": renderer}))
    painted = stage.desired(ctx, FIXTURE_LISTING, None)
    assert scene_hash(changed, changed.works[0]) != scene_hash(painted, painted.works[0])


def test_semantic_scene_identity_ignores_yaml_formatting_and_design_metadata(workspace_root):
    from etsy_listings.core.engine import execute

    workspace, _ = listing_with_marigold(workspace_root, prepare=True)
    ctx = a_context(workspace_root)
    stage = RenderStage()
    first = execute(ctx, build_plan(ctx, FIXTURE_LISTING, a_lock(), (stage,)), a_lock())
    path = workspace.template_config_file("shirt")
    path.write_text("# formatting only\n" + path.read_text(encoding="utf-8"), encoding="utf-8")
    design = workspace.design_file("take-a-hike")
    design.write_bytes(design.read_bytes() + b"ignored png trailer")
    assert not build_plan(ctx, FIXTURE_LISTING, first, (stage,)).plan.stage_plans[0].will_run


def test_one_missing_multiple_archive_blocks_the_whole_listing(workspace_root):
    workspace = marigold_template(workspace_root, "multiple")
    ListingDocuments(workspace).edit(
        FIXTURE_LISTING, lambda document: {**document, "media": [{"template": "shirt"}]}
    )
    config = workspace.load_template_config("shirt")
    artifacts = Artifacts(workspace)
    inputs = artifacts.saved_inputs("shirt", evidence={p.id: "a" * 64 for p in config.placements})
    generation = artifacts.publish(
        "shirt",
        inputs,
        {p.id: material_maps((64, 64)) for p in config.placements},
        current_inputs=lambda: inputs,
    )
    workspace.template_map_file("shirt", generation.generation_id, "right-shirt").unlink()
    refusal = (
        build_plan(a_context(workspace_root), FIXTURE_LISTING, a_lock(), (RenderStage(),))
        .plan.stage_plans[0]
        .blocked
    )
    assert refusal is not None
    assert "prepare" in refusal.lower()
    assert refusal == WorkspaceFacts.gather(workspace).templates["shirt"].preparation_error
    assert not workspace.render_file(FIXTURE_LISTING, "shirt", None).exists()


def test_shared_colour_scenes_use_each_target_photo_without_inference(workspace_root):
    from etsy_listings.core.engine import execute
    from etsy_listings.core.render import (
        MaterialLayer,
        encode_png,
        load_design,
        load_template_base,
        render_marigold_scene,
    )

    workspace = marigold_template(workspace_root, "colour-matrix")
    ListingDocuments(workspace).edit(
        FIXTURE_LISTING,
        lambda document: {
            **document,
            "colors": ["navy", "ivory"],
            "media": [{"template": "shirt", "colour": colour} for colour in ["navy", "ivory"]],
        },
    )
    artifacts = Artifacts(workspace)
    inputs = artifacts.saved_inputs("shirt", evidence={None: "a" * 64})
    maps = material_maps((64, 64))
    artifacts.publish("shirt", inputs, {None: maps}, current_inputs=lambda: inputs)
    ctx = a_context(workspace_root)
    stage = RenderStage()
    desired = stage.desired(ctx, FIXTURE_LISTING, None)
    execute(ctx, build_plan(ctx, FIXTURE_LISTING, a_lock(), (stage,)), a_lock())
    for work in desired.works:
        expected = render_marigold_scene(
            load_template_base(work.base_image),
            [MaterialLayer(load_design(work.layers[0].design), maps)],
            appearance=work.appearance,
        )
        assert work.output.read_bytes() == encode_png(expected)
    assert desired.works[0].render_identity != desired.works[1].render_identity


def test_unprepared_reference_can_be_saved_as_reusable_listing_template(workspace_root):
    from etsy_listings.core.application.listing_template_library import create_listing_template
    from etsy_listings.core.application.workspace_locks import WorkspaceLocks

    workspace, _ = listing_with_marigold(workspace_root)
    result = create_listing_template(
        workspace,
        "ready-for-artwork",
        from_listing=FIXTURE_LISTING,
        from_template=None,
        locks=WorkspaceLocks(),
    )
    assert result.saved
    assert workspace.load_listing_template("ready-for-artwork").media[0].template == "shirt"
    assert (
        build_plan(a_context(workspace_root), FIXTURE_LISTING, a_lock(), (RenderStage(),))
        .plan.stage_plans[0]
        .blocked
        == "Prepare the template first"
    )


def test_full_pipeline_repeat_apply_is_idle_and_render_recovery_does_not_reupload(
    workspace_root,
):
    from etsy_listings.core.engine import apply_listings, plan_listings
    from etsy_listings.core.workspace.workspace import remove_tree

    from tests.support.pipeline import a_deployable_context, real_stages

    ctx = a_deployable_context(workspace_root)
    workspace, _ = listing_with_marigold(workspace_root, prepare=True)
    first = apply_listings(ctx, [FIXTURE_LISTING], real_stages())
    assert first.outcomes[0].ok, first.outcomes[0].error
    assert not any(
        stage.will_run
        for stage in plan_listings(ctx, [FIXTURE_LISTING], real_stages())
        .outcomes[0]
        .planned.plan.stage_plans
    )
    writes = (
        len(ctx.printify.uploads),
        len(ctx.printify.created),
        len(ctx.printify.updated),
        len(ctx.printify.published),
        len(ctx.etsy.uploads),
        len(ctx.etsy.updated),
    )
    repeat = apply_listings(ctx, [FIXTURE_LISTING], real_stages())
    assert repeat.outcomes[0].ok, repeat.outcomes[0].error
    assert (
        len(ctx.printify.uploads),
        len(ctx.printify.created),
        len(ctx.printify.updated),
        len(ctx.printify.published),
        len(ctx.etsy.uploads),
        len(ctx.etsy.updated),
    ) == writes
    remove_tree(workspace.render_file(FIXTURE_LISTING, "shirt", None).parent)
    planned = plan_listings(ctx, [FIXTURE_LISTING], real_stages()).outcomes[0].planned.plan
    assert [stage.stage for stage in planned.stage_plans if stage.will_run] == [
        "render",
        "etsy_media",
    ]
    repaired = apply_listings(ctx, [FIXTURE_LISTING], real_stages())
    assert repaired.outcomes[0].ok, repaired.outcomes[0].error
    assert (
        len(ctx.printify.uploads),
        len(ctx.printify.created),
        len(ctx.printify.updated),
        len(ctx.printify.published),
        len(ctx.etsy.uploads),
    ) == writes[:5]

"""Running the pipeline over a set of listings, with no terminal involved.

PRD 16's continue-on-error used to be a private CLI helper, so the only way to
check that one bad listing did not halt the batch was to invoke the command
and grep its stdout. These assert against the :class:`RunReport` instead --
the same object the UI will serialise in Phase 5.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from etsy_listings.clients.printify.fakes import FakeCatalogClient, FakePrintifyClient
from etsy_listings.clients.printify.models import Blueprint
from etsy_listings.clients.printify.transport import PrintifyApiError, PrintifyAuthError
from etsy_listings.config.secrets import PRINTIFY_TOKEN_VAR, MissingCredentialError
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.events import (
    EngineListingFailed,
    EngineListingPlanned,
    EngineRunEvent,
    EngineStageChecking,
    EngineStagePlanned,
)
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.plan import PlannedRun
from etsy_listings.engine.run import (
    StalePlanError,
    apply_listings,
    plan_fingerprint,
    plan_listings,
)
from etsy_listings.engine.stages import STAGES
from etsy_listings.engine.stages.render import RenderStage

from tests.support.builders import (
    APPLIED_AT,
    a_context,
    copy_listing,
    set_copy,
    set_shop_id,
    write_design,
)
from tests.support.builders import FIXTURE_LISTING as LISTING


def _ctx(root: Path, **overrides: object) -> RunContext:
    """The catalog is left at the builder's empty default on purpose: the
    fixture workspace has no ``printify.shop_id``, so the product stage blocks
    before it resolves a blueprint -- these tests are about the run, not about
    what a stage does once it can run."""
    return a_context(root, printify=FakePrintifyClient([]), **overrides)  # type: ignore[arg-type]


# ------------------------------------------------------------------ PRD 16


def test_one_bad_listing_does_not_stop_the_rest(workspace_root: Path) -> None:
    """The whole reason `--all` is safe to run over a real catalogue."""
    copy_listing(workspace_root, "broken", garment_profile="no-such-profile")
    copy_listing(workspace_root, "fine")

    report = plan_listings(_ctx(workspace_root), ["broken", "fine", LISTING], STAGES)

    assert [outcome.listing for outcome in report.outcomes] == ["broken", "fine", LISTING]
    assert [outcome.ok for outcome in report.outcomes] == [False, True, True]


def test_a_report_with_any_failure_is_failed(workspace_root: Path) -> None:
    """What the CLI turns into an exit code, and the one thing watching a
    batch go past does not tell you."""
    copy_listing(workspace_root, "broken", garment_profile="no-such-profile")

    report = plan_listings(_ctx(workspace_root), ["broken", LISTING], STAGES)

    assert report.failed
    assert [outcome.listing for outcome in report.failures] == ["broken"]


def test_a_clean_batch_reports_no_failure(workspace_root: Path) -> None:
    report = plan_listings(_ctx(workspace_root), [LISTING], STAGES)

    assert not report.failed
    assert report.outcomes[0].planned is not None


def test_a_failure_carries_the_message_not_a_stack(workspace_root: Path) -> None:
    """The error is the whole useful output -- that is what `UserFacingError`
    means, and the run module catches nothing else."""
    copy_listing(workspace_root, "broken", garment_profile="no-such-profile")

    report = plan_listings(_ctx(workspace_root), ["broken"], STAGES)

    error = report.outcomes[0].error
    assert error is not None
    assert "no-such-profile" in str(error)
    assert report.outcomes[0].planned is None


class _RefusingCatalog(FakeCatalogClient):
    """A catalog whose every read is refused, the way a live one refuses.

    Subclassed rather than made configurable on the fake itself: refusing is
    not behaviour Printify *has*, it is what the transport produces out of a
    500 or a revoked token, and a fake that could be told to refuse invites
    tests that assert against a flag instead of against an error.
    """

    def __init__(self, error: Exception) -> None:
        super().__init__([], {}, {})
        self._error = error

    def blueprints(self) -> list[Blueprint]:
        raise self._error


def _configured(root: Path) -> Path:
    """A workspace the product stage will actually run in, so that the
    catalog is reached rather than blocked in front of."""
    set_shop_id(root, 28819281)
    set_copy(root, title="Take a Hike", description="A shirt for walking.")
    write_design(root, (4500, 5400))
    return root


@pytest.mark.parametrize(
    "error",
    [
        PrintifyApiError(500, code=None, reason="upstream failure"),
        PrintifyAuthError(401),
        MissingCredentialError(
            PRINTIFY_TOKEN_VAR, Path(".env"), "read the catalog", "Generate one at printify.com."
        ),
    ],
    ids=["api-refused", "token-rejected", "no-credential"],
)
def test_a_client_refusal_fails_its_listing_rather_than_the_run(
    workspace_root: Path, error: Exception
) -> None:
    """PRD 16 covers the API refusing, not only the config being wrong.

    These three used to be plain ``RuntimeError``s, and ``run`` catches only
    :class:`UserFacingError` -- so a 500, a revoked token or an unset variable
    on the third listing of a fifty-listing `--all` ended the batch with a
    traceback and lost the forty-seven behind it. What makes the difference is
    the *type*; the messages were always written for a user to read.
    """
    _configured(workspace_root)
    copy_listing(workspace_root, "second")

    report = plan_listings(
        _ctx(workspace_root, catalog=_RefusingCatalog(error)), [LISTING, "second"], STAGES
    )

    assert [outcome.listing for outcome in report.outcomes] == [LISTING, "second"]
    assert report.failed
    assert [outcome.ok for outcome in report.outcomes] == [False, False], (
        "the run reached the second listing instead of dying on the first"
    )


def test_a_client_refusal_arrives_as_its_message(workspace_root: Path) -> None:
    """The refusal Printify explained is the whole of what the user needs."""
    _configured(workspace_root)

    report = plan_listings(
        _ctx(
            workspace_root,
            catalog=_RefusingCatalog(PrintifyApiError(422, code=8254, reason="shop not connected")),
        ),
        [LISTING],
        STAGES,
    )

    error = report.outcomes[0].error
    assert error is not None
    assert "shop not connected" in str(error)


def test_an_unreadable_lockfile_redoes_the_work_instead_of_ending_the_run(
    workspace_root: Path,
) -> None:
    """A lockfile some other version wrote, or a truncated one.

    The render stage used to index its subtree directly, so a document missing
    a key raised `KeyError` -- not a `UserFacingError`, so it escaped the run
    loop and took the batch with it. Decoding is the lockfile's job now, and a
    document it cannot read means what "never applied" already means: redo the
    work.
    """
    copy_listing(workspace_root, "second")
    for name in (LISTING, "second"):
        path = workspace_root / "listings" / name / "state.lock.json"
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "tool_version": "0.0.0",
                    "applied_at": APPLIED_AT,
                    "applied": {"render": {"scenes": ["gone"]}},
                }
            ),
            encoding="utf-8",
        )

    report = plan_listings(_ctx(workspace_root), [LISTING, "second"], STAGES)

    assert [outcome.ok for outcome in report.outcomes] == [True, True]
    planned = report.outcomes[0].planned
    assert planned is not None
    render = next(sp for sp in planned.plan.stage_plans if sp.stage == "render")
    assert render.will_run
    assert render.reason == "no previous render"


# ------------------------------------------------------------------- sinks


def test_planned_fires_per_listing_as_the_run_goes(workspace_root: Path) -> None:
    """Output has to interleave with the work: a `--all` run over fifty
    listings should print as it goes, not save it all for the end."""
    copy_listing(workspace_root, "fine")
    seen: list[str] = []

    def capture(event: EngineRunEvent) -> None:
        if isinstance(event, EngineListingPlanned):
            seen.append(event.listing)

    plan_listings(
        _ctx(workspace_root),
        ["fine", LISTING],
        STAGES,
        on_event=capture,
    )

    assert seen == ["fine", LISTING]


def test_failure_sink_fires_only_for_the_listing_that_failed(workspace_root: Path) -> None:
    copy_listing(workspace_root, "broken", garment_profile="no-such-profile")
    planned: list[str] = []
    failed: list[str] = []

    def capture(event: EngineRunEvent) -> None:
        if isinstance(event, EngineListingPlanned):
            planned.append(event.listing)
        elif isinstance(event, EngineListingFailed):
            failed.append(event.listing)

    plan_listings(
        _ctx(workspace_root),
        ["broken", LISTING],
        STAGES,
        on_event=capture,
    )

    assert failed == ["broken"]
    assert planned == [LISTING]


def test_apply_announces_a_listing_before_it_does_the_work(workspace_root: Path) -> None:
    """`on_planned` fires between planning and executing. That is the only
    point at which the plan is known and none of its progress events have been
    emitted yet, which is what lets the CLI print a header and its blocked
    warnings above the work they frame."""
    order: list[str] = []
    ctx = _ctx(workspace_root, on_event=lambda event: order.append(f"event:{event.message}"))

    def capture(event: EngineRunEvent) -> None:
        if isinstance(event, EngineListingPlanned):
            order.append(f"planned:{event.listing}")

    apply_listings(
        ctx,
        [LISTING],
        STAGES,
        on_event=capture,
    )

    assert order[0] == f"planned:{LISTING}"
    assert any(entry.startswith("event:") for entry in order[1:])


# -------------------------------------------------------- lockfile lifecycle


def test_apply_writes_a_lockfile_per_listing(workspace_root: Path) -> None:
    """Per listing rather than at the end of the batch: that is what makes a
    half-finished `--all` resumable."""
    copy_listing(workspace_root, "fine")

    apply_listings(_ctx(workspace_root), ["fine", LISTING], STAGES)

    for name in ("fine", LISTING):
        assert (workspace_root / "listings" / name / "state.lock.json").is_file()


def test_a_failed_listing_writes_no_lockfile(workspace_root: Path) -> None:
    copy_listing(workspace_root, "broken", garment_profile="no-such-profile")

    apply_listings(_ctx(workspace_root), ["broken"], STAGES)

    assert not (workspace_root / "listings" / "broken" / "state.lock.json").is_file()


def test_a_second_apply_reads_the_lockfile_the_first_one_wrote(workspace_root: Path) -> None:
    """The run module owns the lockfile's lifecycle, so idempotency has to
    hold through it and not only through `execute`."""
    apply_listings(_ctx(workspace_root), [LISTING], STAGES)
    first = Lockfile.read(workspace_root / "listings" / LISTING / "state.lock.json")

    report = plan_listings(_ctx(workspace_root), [LISTING], STAGES)

    assert first is not None
    planned: PlannedRun | None = report.outcomes[0].planned
    assert planned is not None
    assert not planned.plan.has_changes, "an unchanged listing re-plans as no work"


# ------------------------------------------------------------ plan-time events


def test_stage_checking_and_stage_planned_fire_once_per_stage_in_pipeline_order(
    workspace_root: Path,
) -> None:
    """A33, decision 2: `build_plan`'s walk reports each stage as it goes,
    in the pipeline's own order -- A21 left A3's fan-out unbuilt, so that
    order is genuinely the order stages resolve in."""
    checking: list[str] = []
    resolved: list[str] = []

    def capture(event: EngineRunEvent) -> None:
        if isinstance(event, EngineStageChecking):
            checking.append(event.stage)
        elif isinstance(event, EngineStagePlanned):
            resolved.append(event.stage_plan.stage)

    plan_listings(
        _ctx(workspace_root),
        [LISTING],
        STAGES,
        on_event=capture,
    )

    expected = [stage.name for stage in STAGES]
    assert checking == expected
    assert resolved == expected


def test_stage_planned_carries_the_resolved_stage_plan(workspace_root: Path) -> None:
    seen: list[object] = []

    def capture(event: EngineRunEvent) -> None:
        if isinstance(event, EngineStagePlanned):
            seen.append(event.stage_plan)

    plan_listings(
        _ctx(workspace_root),
        [LISTING],
        [RenderStage()],
        on_event=capture,
    )

    assert len(seen) == 1
    assert seen[0].stage == "render"  # type: ignore[attr-defined]
    assert seen[0].will_run  # type: ignore[attr-defined]


# ---------------------------------------------------------- expect / stale plans


def test_apply_with_a_matching_fingerprint_applies_normally(workspace_root: Path) -> None:
    ctx = _ctx(workspace_root)
    planned = plan_listings(ctx, [LISTING], [RenderStage()]).outcomes[0].planned
    assert planned is not None
    fingerprint = plan_fingerprint(planned.plan)

    report = apply_listings(ctx, [LISTING], [RenderStage()], expect={LISTING: fingerprint})

    assert not report.failed
    assert (workspace_root / "listings" / LISTING / "state.lock.json").is_file()


def test_a_stale_fingerprint_refuses_before_any_write(workspace_root: Path) -> None:
    """A31: acting on a plan that no longer describes the current state --
    here, any fingerprint that is not the real one -- must not run a single
    stage."""
    ctx = _ctx(workspace_root)

    report = apply_listings(ctx, [LISTING], [RenderStage()], expect={LISTING: "sha256:" + "0" * 64})

    assert report.failed
    error = report.outcomes[0].error
    assert isinstance(error, StalePlanError)
    assert error.listing == LISTING
    assert error.planned is not None, "the fresh plan travels with the refusal"
    assert not (workspace_root / "listings" / LISTING / "state.lock.json").is_file()


def test_a_stale_listing_does_not_stop_the_rest_of_the_batch(workspace_root: Path) -> None:
    """PRD 16, still: a stale plan is a refusal like any other."""
    copy_listing(workspace_root, "fine")
    ctx = _ctx(workspace_root)

    report = apply_listings(
        ctx,
        [LISTING, "fine"],
        [RenderStage()],
        expect={LISTING: "sha256:" + "0" * 64},
    )

    assert [outcome.listing for outcome in report.outcomes] == [LISTING, "fine"]
    assert isinstance(report.outcomes[0].error, StalePlanError)
    assert report.outcomes[1].ok
    assert (workspace_root / "listings" / "fine" / "state.lock.json").is_file()


def test_a_listing_with_no_entry_in_expect_is_never_checked(workspace_root: Path) -> None:
    """Every CLI call today: `apply` with no prior `plan` to compare against.
    `expect` only applies to listings it actually names."""
    ctx = _ctx(workspace_root)

    report = apply_listings(ctx, [LISTING], [RenderStage()], expect={})

    assert not report.failed
    assert (workspace_root / "listings" / LISTING / "state.lock.json").is_file()

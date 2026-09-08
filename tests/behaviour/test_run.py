"""Running the pipeline over a set of listings, with no terminal involved.

PRD 16's continue-on-error used to be a private CLI helper, so the only way to
check that one bad listing did not halt the batch was to invoke the command
and grep its stdout. These assert against the :class:`RunReport` instead --
the same object the UI will serialise in Phase 5.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from etsy_listings.catalog.fakes import FakeCatalogClient
from etsy_listings.clients.printify.fakes import FakePrintifyClient
from etsy_listings.engine.context import RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.engine.plan import PlannedRun
from etsy_listings.engine.run import apply_listings, plan_listings
from etsy_listings.engine.stages import STAGES
from etsy_listings.workspace.workspace import Workspace

LISTING = "take-a-hike"


def _catalog() -> FakeCatalogClient:
    """Empty on purpose. The fixture workspace has no ``printify.shop_id``, so
    the product stage blocks before it resolves a blueprint -- these tests are
    about the run, not about what a stage does once it can run."""
    return FakeCatalogClient(blueprints=[], providers_by_blueprint={}, variants_by_key={})


def _ctx(root: Path) -> RunContext:
    return RunContext(
        workspace=Workspace.discover(root_override=root),
        catalog=_catalog(),
        printify=FakePrintifyClient([]),
    )


def _second_listing(root: Path, name: str, **overrides: object) -> None:
    """A copy of the fixture listing, filed under another name."""
    source = root / "listings" / LISTING / "listing.yaml"
    document = yaml.safe_load(source.read_text(encoding="utf-8"))
    document.update(overrides)
    target = root / "listings" / name
    target.mkdir(parents=True, exist_ok=True)
    (target / "listing.yaml").write_text(yaml.safe_dump(document), encoding="utf-8")


# ------------------------------------------------------------------ PRD 16


def test_one_bad_listing_does_not_stop_the_rest(workspace_root: Path) -> None:
    """The whole reason `--all` is safe to run over a real catalogue."""
    _second_listing(workspace_root, "broken", profile="no-such-profile")
    _second_listing(workspace_root, "fine")

    report = plan_listings(_ctx(workspace_root), ["broken", "fine", LISTING], STAGES)

    assert [outcome.listing for outcome in report.outcomes] == ["broken", "fine", LISTING]
    assert [outcome.ok for outcome in report.outcomes] == [False, True, True]


def test_a_report_with_any_failure_is_failed(workspace_root: Path) -> None:
    """What the CLI turns into an exit code, and the one thing watching a
    batch go past does not tell you."""
    _second_listing(workspace_root, "broken", profile="no-such-profile")

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
    _second_listing(workspace_root, "broken", profile="no-such-profile")

    report = plan_listings(_ctx(workspace_root), ["broken"], STAGES)

    error = report.outcomes[0].error
    assert error is not None
    assert "no-such-profile" in str(error)
    assert report.outcomes[0].planned is None


# ------------------------------------------------------------------- sinks


def test_planned_fires_per_listing_as_the_run_goes(workspace_root: Path) -> None:
    """Output has to interleave with the work: a `--all` run over fifty
    listings should print as it goes, not save it all for the end."""
    _second_listing(workspace_root, "fine")
    seen: list[str] = []

    plan_listings(
        _ctx(workspace_root),
        ["fine", LISTING],
        STAGES,
        on_planned=lambda name, planned: seen.append(name),
    )

    assert seen == ["fine", LISTING]


def test_failure_sink_fires_only_for_the_listing_that_failed(workspace_root: Path) -> None:
    _second_listing(workspace_root, "broken", profile="no-such-profile")
    planned: list[str] = []
    failed: list[str] = []

    plan_listings(
        _ctx(workspace_root),
        ["broken", LISTING],
        STAGES,
        on_planned=lambda name, run: planned.append(name),
        on_failure=lambda name, error: failed.append(name),
    )

    assert failed == ["broken"]
    assert planned == [LISTING]


def test_apply_announces_a_listing_before_it_does_the_work(workspace_root: Path) -> None:
    """`on_planned` fires between planning and executing. That is the only
    point at which the plan is known and none of its progress events have been
    emitted yet, which is what lets the CLI print a header and its blocked
    warnings above the work they frame."""
    order: list[str] = []
    ctx = RunContext(
        workspace=Workspace.discover(root_override=workspace_root),
        catalog=_catalog(),
        printify=FakePrintifyClient([]),
        on_event=lambda event: order.append(f"event:{event.message}"),
    )

    apply_listings(
        ctx, [LISTING], STAGES, on_planned=lambda name, run: order.append(f"planned:{name}")
    )

    assert order[0] == f"planned:{LISTING}"
    assert any(entry.startswith("event:") for entry in order[1:])


# -------------------------------------------------------- lockfile lifecycle


def test_apply_writes_a_lockfile_per_listing(workspace_root: Path) -> None:
    """Per listing rather than at the end of the batch: that is what makes a
    half-finished `--all` resumable."""
    _second_listing(workspace_root, "fine")

    apply_listings(_ctx(workspace_root), ["fine", LISTING], STAGES)

    for name in ("fine", LISTING):
        assert (workspace_root / "listings" / name / "state.lock.json").is_file()


def test_a_failed_listing_writes_no_lockfile(workspace_root: Path) -> None:
    _second_listing(workspace_root, "broken", profile="no-such-profile")

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

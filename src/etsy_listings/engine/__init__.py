"""What decides and what executes: the stage pipeline, the three-way diff and
the lockfile. A1/A2/A3.

**Only this module computes a diff.** ``cli`` renders the resulting
:class:`Plan` as text and ``ui`` will serialise the same object as JSON;
neither compares state itself, which is what guarantees the PRD's "one set of
rules regardless of route" (PRD 20). Nothing here formats output or talks HTTP.

:func:`build_plan` walks :data:`STAGES` in order, asking each for its desired
and live state, handing it its own lockfile subtree, and letting the stage's
own ``plan()`` compare the three. It returns a :class:`PlannedRun`: the
:class:`Plan` that ``cli`` and ``ui`` render, plus the states it resolved
getting there. :func:`execute` consumes that rather than asking every stage a
second time -- strictly sequentially, because ``apply`` never parallelises
writes (A3).

:func:`plan_listings` and :func:`apply_listings` are the layer above: a whole
run over a set of listings, owning each lockfile's lifecycle and PRD 16's
continue-on-error. Entry points call those and format the
:class:`RunReport`; ``build_plan``/``execute`` remain available for a caller
holding one listing's lockfile itself.

A stage that cannot run says so with a :class:`Blocked`, never an exception:
a refusal is something ``plan`` must report, and an exception unwinds the walk
and takes the other stages' plans with it.
"""

from etsy_listings.engine.apply import execute
from etsy_listings.engine.change import (
    Action,
    Change,
    Drift,
    FieldChange,
    ListChange,
    MediaChange,
    Plan,
    PriceChange,
    StagePlan,
    drift,
    scalar,
    sequence,
)
from etsy_listings.engine.context import Event, EventSink, RunContext, Swatch
from etsy_listings.engine.lock import (
    SCHEMA_VERSION,
    Lockfile,
    StageApplyResult,
    canonical_hash,
    hash_file,
    to_workspace_relative_posix,
)
from etsy_listings.engine.plan import PlannedRun, StageState, build_plan
from etsy_listings.engine.run import (
    FailureSink,
    ListingOutcome,
    PlannedSink,
    RunReport,
    apply_listings,
    plan_listings,
)
from etsy_listings.engine.stage import (
    AnyStage,
    Blocked,
    Stage,
    StageBlockedError,
)
from etsy_listings.engine.stages import STAGES

__all__ = [
    # Running the pipeline over a set of listings -- what `cli` calls, and
    # what the UI will. Continue-on-error and the lockfile's lifecycle live
    # behind these two (PRD 16), not in the entry point that drives them.
    "plan_listings",
    "apply_listings",
    "RunReport",
    "ListingOutcome",
    "PlannedSink",
    "FailureSink",
    # One listing at a time, for a caller that owns its own lockfile.
    "build_plan",
    "execute",
    "STAGES",
    # What planning hands to applying: the plan, and the state behind it.
    "PlannedRun",
    "StageState",
    # What a stage is (A1: one protocol, order encodes dependency).
    "Stage",
    "AnyStage",
    "StageApplyResult",
    "Blocked",
    "StageBlockedError",
    # What plan produces and cli/ui consume -- never comparing state themselves.
    "Plan",
    "StagePlan",
    "Action",
    "Change",
    "FieldChange",
    "ListChange",
    "MediaChange",
    "PriceChange",
    "Drift",
    # The shared comparison helpers each stage's own plan() is written with.
    "scalar",
    "sequence",
    "drift",
    # state.lock.json, and the hashing helpers everything must go through.
    "Lockfile",
    "canonical_hash",
    "hash_file",
    "to_workspace_relative_posix",
    "SCHEMA_VERSION",
    # What a stage is handed, and how it reports progress while applying.
    "RunContext",
    "Event",
    "EventSink",
    "Swatch",
]

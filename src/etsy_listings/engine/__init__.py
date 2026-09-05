"""What decides and what executes: the stage pipeline, the three-way diff and
the lockfile. A1/A2/A3.

**Only this module computes a diff.** ``cli`` renders the resulting
:class:`Plan` as text and ``ui`` will serialise the same object as JSON;
neither compares state itself, which is what guarantees the PRD's "one set of
rules regardless of route" (PRD 20). Nothing here formats output or talks HTTP.

:func:`build_plan` walks :data:`STAGES` in order, asking each for its desired,
last-applied and live state and letting the stage's own ``plan()`` compare
them. :func:`execute` then runs the ones that need to run -- strictly
sequentially, because ``apply`` never parallelises writes (A3).
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
    canonical_hash,
    to_workspace_relative_posix,
)
from etsy_listings.engine.plan import build_plan
from etsy_listings.engine.stage import AnyStage, Stage, StageApplyResult
from etsy_listings.engine.stages import STAGES

__all__ = [
    # The two entry points, and the pipeline they walk.
    "build_plan",
    "execute",
    "STAGES",
    # What a stage is (A1: one protocol, order encodes dependency).
    "Stage",
    "AnyStage",
    "StageApplyResult",
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
    # state.lock.json, and the single hashing helper everything must go through.
    "Lockfile",
    "canonical_hash",
    "to_workspace_relative_posix",
    "SCHEMA_VERSION",
    # What a stage is handed, and how it reports progress while applying.
    "RunContext",
    "Event",
    "EventSink",
    "Swatch",
]

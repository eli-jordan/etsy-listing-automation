"""What an AI-run test needs: a provider that answers all three tasks of the
chain, a seeded Etsy market, the three prompt files, and a wait.

:class:`ChainProvider` tells the tasks apart by their response schema --
the one thing about a :class:`~etsy_listings.ai.models.ProviderTask` that
says which feature asked. A task can be made to fail, or to block on a gate
until the test opens it or the run's cancel event is set, which is how a
test holds a run at one step. A blocked call that sees the cancel event
raises :class:`~etsy_listings.ai.errors.ProviderCancelledError`, as the real
adapters do once ``run_managed`` has killed the process tree.
"""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from etsy_listings.ai.brief import BRIEF_RESPONSE_SCHEMA
from etsy_listings.ai.errors import ProviderCancelledError
from etsy_listings.ai.market_queries import MARKET_QUERIES_RESPONSE_SCHEMA
from etsy_listings.ai.models import (
    Deadline,
    ProviderReadiness,
    ProviderTask,
    RawProviderResult,
    RepairContext,
)
from etsy_listings.clients.etsy.fakes import FakeEtsyMarketClient, market_listing
from etsy_listings.ui.airuns.registry import AiRun
from etsy_listings.workspace.layout import (
    BRIEF_PROMPT_FILE,
    MARKET_QUERIES_PROMPT_FILE,
    PROMPTS_DIR,
    SEO_PROMPT_FILE,
)

Task = Literal["brief", "queries", "seo"]

TODAY = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
QUERIES = ("retro sunset hiking shirt", "mountain sunset tee", "hiking gift shirt")
DRAFTED_BRIEF = "Retro sunset over mountains; the text reads TAKE A HIKE."


def proposal_payload() -> str:
    return json.dumps(
        {
            "titles": ["Retro Sunset Hike Tee", "Take A Hike Graphic Shirt", "Mountain Trail Tee"],
            "tags": [f"tag{i}" for i in range(20)],
            "description_leads": ["lead one", "lead two", "lead three"],
            "rationale": [
                {
                    "phrase": f"phrase {i}",
                    "intent": "core_product",
                    "reason": "because",
                    "used_in": ["title"],
                }
                for i in range(7)
            ],
            "warnings": [],
            "observed_text": "TAKE A HIKE",
        }
    )


def _task_kind(task: ProviderTask) -> Task:
    if task.response_schema is BRIEF_RESPONSE_SCHEMA:
        return "brief"
    if task.response_schema is MARKET_QUERIES_RESPONSE_SCHEMA:
        return "queries"
    return "seo"


@dataclass
class ChainProvider:
    name: str = "codex"
    ready: ProviderReadiness = field(default_factory=lambda: ProviderReadiness(ready=True))
    failures: dict[Task, Exception] = field(default_factory=dict)
    gates: dict[Task, threading.Event] = field(default_factory=dict)
    during: dict[Task, Callable[[], None]] = field(default_factory=dict)
    """Run inside the call, before it answers -- a seller typing mid-draft."""
    calls: list[Task] = field(default_factory=list, init=False)
    tasks: list[ProviderTask] = field(default_factory=list, init=False)
    cancelled: list[Task] = field(default_factory=list, init=False)
    started: defaultdict[Task, threading.Event] = field(
        default_factory=lambda: defaultdict(threading.Event), init=False
    )

    def readiness(self) -> ProviderReadiness:
        return self.ready

    def gate(self, task: Task) -> threading.Event:
        """Hold ``task`` until the returned event is set (or the run is
        cancelled)."""
        self.gates[task] = threading.Event()
        return self.gates[task]

    def generate(
        self,
        task: ProviderTask,
        deadline: Deadline,
        *,
        repair: RepairContext | None = None,
        cancel_event: threading.Event | None = None,
    ) -> RawProviderResult:
        kind = _task_kind(task)
        self.calls.append(kind)
        self.tasks.append(task)
        self.started[kind].set()
        gate = self.gates.get(kind)
        while gate is not None and not gate.wait(0.01):
            if cancel_event is not None and cancel_event.is_set():
                self.cancelled.append(kind)
                raise ProviderCancelledError(self.name)
        if kind in self.during:
            self.during[kind]()
        if kind in self.failures:
            raise self.failures[kind]
        answers = {
            "brief": json.dumps({"brief": DRAFTED_BRIEF}),
            "queries": json.dumps({"queries": list(QUERIES)}),
            "seo": proposal_payload(),
        }
        return RawProviderResult(provider=self.name, raw_output=answers[kind])

    def task(self, kind: Task) -> ProviderTask:
        return next(t for t, k in zip(self.tasks, self.calls, strict=True) if k == kind)


def seed_prompts(root: Path) -> None:
    prompts = root / PROMPTS_DIR
    prompts.mkdir(parents=True, exist_ok=True)
    for name in (SEO_PROMPT_FILE, BRIEF_PROMPT_FILE, MARKET_QUERIES_PROMPT_FILE):
        (prompts / name).write_text(f"The seller's {name}.\n", encoding="utf-8")


def seeded_market(*, comparable: bool = True) -> FakeEtsyMarketClient:
    """Three listings, each found by one of :data:`QUERIES` -- or searches
    that find nothing, when ``comparable`` is false."""
    fake = FakeEtsyMarketClient()
    if comparable:
        created = int(TODAY.timestamp()) - 100 * 86_400
        for listing_id, query in enumerate(QUERIES, start=1):
            fake.seed_listing(
                market_listing(
                    listing_id,
                    title=f"{query.title()} Tee",
                    tags=(query, "hiking gift"),
                    num_favorers=10 * listing_id,
                    views=100 * listing_id,
                    original_creation_timestamp=created,
                ),
                reviews=listing_id,
            )
            fake.seed_search(query, [listing_id])
    return fake


def wait_until_finished(run: AiRun, *, timeout: float = 15.0) -> AiRun:
    deadline = time.monotonic() + timeout
    while not run.finished:
        if time.monotonic() > deadline:
            raise AssertionError(f"AI run {run.id} never finished: {run.events}")
        time.sleep(0.01)
    return run


def wait_for(condition: Callable[[], bool], *, timeout: float = 15.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("condition never became true")
        time.sleep(0.01)

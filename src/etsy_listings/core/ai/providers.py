"""The provider boundary ``ai/orchestrator.py`` drives, and ``FakeAiProvider``."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Protocol, override, runtime_checkable

from etsy_listings.core.ai.models import (
    Deadline,
    ProviderReadiness,
    ProviderTask,
    RawProviderResult,
    RepairContext,
)


@runtime_checkable
class AiProvider(Protocol):
    def readiness(self) -> ProviderReadiness: ...

    def generate(
        self,
        task: ProviderTask,
        deadline: Deadline,
        *,
        repair: RepairContext | None = None,
        cancel_event: threading.Event | None = None,
    ) -> RawProviderResult: ...


@dataclass
class FakeAiProvider(AiProvider):
    name: str
    responses: list[str] = field(default_factory=list)
    ready: ProviderReadiness = field(default_factory=lambda: ProviderReadiness(ready=True))
    tasks: list[ProviderTask] = field(default_factory=list, init=False)
    repairs: list[RepairContext | None] = field(default_factory=list, init=False)
    cancel_events: list[threading.Event | None] = field(default_factory=list, init=False)

    @override
    def readiness(self) -> ProviderReadiness:
        return self.ready

    @override
    def generate(
        self,
        task: ProviderTask,
        deadline: Deadline,
        *,
        repair: RepairContext | None = None,
        cancel_event: threading.Event | None = None,
    ) -> RawProviderResult:
        self.tasks.append(task)
        self.repairs.append(repair)
        self.cancel_events.append(cancel_event)
        if not self.responses:
            raise AssertionError(
                f"FakeAiProvider {self.name!r} was asked to generate with no queued "
                f"response left -- give it one more entry in `responses`"
            )
        return RawProviderResult(provider=self.name, raw_output=self.responses.pop(0))

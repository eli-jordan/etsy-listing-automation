"""Host-injected native runtime and worker boundaries."""

from collections.abc import Callable
from contextlib import AbstractContextManager, nullcontext
from pathlib import Path
from typing import Protocol

from etsy_listings.core.preparation.distribution.src.marigold_worker.protocol import (
    InferenceResult,
    Progress,
)
from etsy_listings.core.preparation.runtime import Capability
from etsy_listings.core.preparation.worker_client import InferenceCall


class InferenceWorker(Protocol):
    def infer(
        self,
        call: InferenceCall,
        *,
        progress: Callable[[Progress], None] | None = None,
        dispatch_guard: Callable[[], AbstractContextManager[None]] = nullcontext,
    ) -> InferenceResult: ...
    def cancel(self, request_id: str) -> None: ...
    def close(self) -> None: ...


class PreparationRuntime(Protocol):
    def inspect(self) -> Capability: ...
    def selection(self, version: str, *, installation_id: str | None = None) -> Capability: ...
    def worker(self, selected: Capability, *, cache_root: Path) -> InferenceWorker: ...

from __future__ import annotations

import re
import threading
import time
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from etsy_listings.core.ai.host import LOCAL_CLI_HOST, CliHost
from etsy_listings.core.ai.models import Deadline
from etsy_listings.core.ai.process import CliProcessError
from etsy_listings.core.config.settings import ProviderName

CACHE_SECONDS = 30 * 60
REFRESH_SECONDS = 15
CLAUDE_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5")
CLAUDE_EFFORTS = ("low", "medium", "high", "xhigh", "max")
GROK_EFFORTS = ("low", "medium", "high")


class ModelChoice(BaseModel):
    model_config = ConfigDict(frozen=True)
    id: str
    label: str
    efforts: tuple[str, ...] = ()


class ProviderCatalog(BaseModel):
    model_config = ConfigDict(frozen=True)
    models: tuple[ModelChoice, ...] = ()
    efforts: tuple[str, ...] = ()
    problem: str | None = None


class ModelCatalogs(BaseModel):
    providers: dict[ProviderName, ProviderCatalog] = Field(default_factory=dict)
    cache_seconds: int = CACHE_SECONDS


class ModelDiscovery:
    """One process's discovery owner. Concurrent reads share a single refresh.

    A failure is cached too, preventing repeated probes on every page read.
    Explicit Refresh retries immediately. Last successful choices survive a
    failure, marked with its problem; saved choices belong to settings alone.

    ``host`` is where the CLIs are found and run. ``None`` is this machine,
    read when the owner is constructed rather than bound as a default, so
    host tests can make every server's discovery hermetic at once.
    """

    def __init__(
        self, *, monotonic: Callable[[], float] = time.monotonic, host: CliHost | None = None
    ) -> None:
        self._monotonic = monotonic
        self._host = LOCAL_CLI_HOST if host is None else host
        self._expires = 0.0
        self._cached: ModelCatalogs | None = None
        self._lock = threading.Lock()
        self._cancel = threading.Event()
        self._refreshing = False
        self._worker: threading.Thread | None = None

    def start(self) -> None:
        with self._lock:
            if self._worker is not None and self._worker.is_alive():
                return
            self._cancel.clear()
            self._worker = threading.Thread(
                target=self.read, name="ai-model-discovery", daemon=True
            )
            self._worker.start()

    def stop(self, *, timeout: float = 6.0) -> None:
        self._cancel.set()
        with self._lock:
            worker = self._worker
        if worker is not None:
            worker.join(timeout=timeout)

    def read(self, *, refresh: bool = False) -> ModelCatalogs:
        with self._lock:
            if self._cancel.is_set():
                return self._snapshot_locked(
                    "Model discovery stopped. Restart the server to retry."
                )
            if self._refreshing:
                return self._snapshot_locked(
                    "Model discovery is in progress. Refresh to check again."
                )
            if not refresh and self._cached is not None and self._monotonic() < self._expires:
                return self._cached.model_copy(deep=True)
            previous = self._cached.providers if self._cached is not None else {}
            self._refreshing = True
        try:
            catalogs: dict[ProviderName, ProviderCatalog] = {}
            deadline = Deadline.starting_now(seconds=REFRESH_SECONDS, clock=self._monotonic)
            for name in ("codex", "grok"):
                try:
                    catalogs[name] = _discover(self._host, name, deadline, self._cancel)
                except (OSError, CliProcessError, ValueError):
                    kept = previous.get(name, ProviderCatalog())
                    catalogs[name] = kept.model_copy(
                        update={
                            "problem": f"Could not read the {name} model list. "
                            "Refresh to try again."
                        }
                    )
            catalogs["claude"] = _claude()
            with self._lock:
                self._cached = ModelCatalogs(providers=catalogs)
                self._expires = self._monotonic() + CACHE_SECONDS
                return self._cached.model_copy(deep=True)
        finally:
            with self._lock:
                self._refreshing = False

    def _snapshot_locked(self, problem: str) -> ModelCatalogs:
        cached = (
            self._cached.model_copy(deep=True)
            if self._cached
            else ModelCatalogs(providers={"claude": _claude()})
        )
        for name in ("codex", "grok"):
            cached.providers[name] = cached.providers.get(name, ProviderCatalog()).model_copy(
                update={"problem": problem}
            )
        return cached


def _claude() -> ProviderCatalog:
    return ProviderCatalog(
        models=tuple(ModelChoice(id=model, label=model) for model in CLAUDE_MODELS),
        efforts=CLAUDE_EFFORTS,
    )


def _discover(
    host: CliHost, name: str, deadline: Deadline, cancel: threading.Event
) -> ProviderCatalog:
    if deadline.expired or cancel.is_set():
        raise ValueError("discovery budget exhausted or discovery stopped")
    binary = host.which(name)
    if binary is None:
        raise OSError(f"{name} was not found")
    argv = [binary, "debug", "models"] if name == "codex" else [binary, "models"]
    result = host.run_managed(
        argv, cwd=Path.cwd(), input_text="", deadline=deadline, cancel_event=cancel
    )
    if result.timed_out or result.cancelled or result.returncode != 0:
        raise ValueError("discovery failed")
    if name == "codex":
        return _codex(result.stdout)
    return _grok(result.stdout)


def _grok(stdout: str) -> ProviderCatalog:
    # Grok 1.0.70: prose preamble, then 'Available models:' with * / - rows.
    _, marker, rows = stdout.partition("Available models:")
    if not marker:
        raise ValueError("unrecognized Grok catalog")
    models = tuple(
        ModelChoice(id=match[1], label=match[1])
        for line in rows.splitlines()
        if (match := re.fullmatch(r"\s*[*-]\s+(\S+)(?:\s+\(default\))?\s*", line))
    )
    if not models:
        raise ValueError("empty Grok catalog")
    return ProviderCatalog(models=models, efforts=GROK_EFFORTS)


class _CodexLevel(BaseModel):
    effort: str


class _CodexModel(BaseModel):
    slug: str
    display_name: str | None = None
    visibility: str | None = None
    supported_reasoning_levels: tuple[_CodexLevel, ...] = ()


class _CodexCatalog(BaseModel):
    """Codex 0.166.0's ``debug models`` output, as far as discovery reads it."""

    models: tuple[_CodexModel, ...]


def _codex(stdout: str) -> ProviderCatalog:
    models = tuple(
        ModelChoice(
            id=row.slug,
            label=row.display_name or row.slug,
            efforts=tuple(
                level.effort for level in row.supported_reasoning_levels if level.effort != "ultra"
            ),
        )
        for row in _CodexCatalog.model_validate_json(stdout).models
        if row.visibility != "hide"
    )
    if not models:
        raise ValueError("empty Codex catalog")
    return ProviderCatalog(
        models=models, efforts=tuple(dict.fromkeys(e for model in models for e in model.efforts))
    )

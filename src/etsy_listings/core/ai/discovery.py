"""Advisory installed-CLI catalogs, cached per host for 30 minutes (ADR-0056).

Only explicit catalog fields are read. Discovery never changes preferences or
starts generation, and no account configuration or credentials are read here.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from etsy_listings.core.config.settings import ProviderName

CACHE_SECONDS = 30 * 60
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
    """

    def __init__(self, *, monotonic: Callable[[], float] = time.monotonic) -> None:
        self._monotonic = monotonic
        self._expires = 0.0
        self._cached: ModelCatalogs | None = None
        self._lock = threading.Lock()

    def read(self, *, refresh: bool = False) -> ModelCatalogs:
        with self._lock:
            if not refresh and self._cached is not None and self._monotonic() < self._expires:
                return self._cached.model_copy(deep=True)
            previous = self._cached.providers if self._cached is not None else {}
            catalogs: dict[ProviderName, ProviderCatalog] = {}
            for name in ("codex", "grok"):
                try:
                    catalogs[name] = _discover(name)
                except (
                    OSError,
                    subprocess.SubprocessError,
                    ValueError,
                    KeyError,
                    TypeError,
                    AttributeError,
                ):
                    kept = previous.get(name, ProviderCatalog())
                    catalogs[name] = kept.model_copy(
                        update={
                            "problem": f"Could not read the {name} model list. "
                            "Refresh to try again."
                        }
                    )
            catalogs["claude"] = ProviderCatalog(
                models=tuple(ModelChoice(id=id, label=id) for id in CLAUDE_MODELS),
                efforts=CLAUDE_EFFORTS,
            )
            self._cached = ModelCatalogs(providers=catalogs)
            self._expires = self._monotonic() + CACHE_SECONDS
            return self._cached.model_copy(deep=True)


def _discover(name: str) -> ProviderCatalog:
    binary = shutil.which(name)
    if binary is None:
        raise OSError(f"{name} was not found")
    argv = [binary, "debug", "models"] if name == "codex" else [binary, "models"]
    result = subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", timeout=15)
    if result.returncode:
        raise ValueError("discovery failed")
    if name == "codex":
        return _codex(json.loads(result.stdout))
    # Grok 1.0.70: prose preamble, then 'Available models:' with * / - rows.
    _, marker, rows = result.stdout.partition("Available models:")
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


def _codex(raw: Any) -> ProviderCatalog:  # noqa: ANN401 - untrusted CLI JSON
    # Codex 0.166.0: models[].slug/display_name/supported_reasoning_levels[].effort.
    models = tuple(
        ModelChoice(
            id=row["slug"],
            label=row.get("display_name", row["slug"]),
            efforts=tuple(
                level["effort"]
                for level in row["supported_reasoning_levels"]
                if level["effort"] != "ultra"
            ),
        )
        for row in raw["models"]
        if row.get("visibility") != "hide"
    )
    if not models:
        raise ValueError("empty Codex catalog")
    return ProviderCatalog(
        models=models, efforts=tuple(dict.fromkeys(e for model in models for e in model.efforts))
    )

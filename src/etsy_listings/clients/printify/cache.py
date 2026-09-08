"""TTL file cache wrapping any :class:`CatalogClient`.

PRD: "the Printify catalog is fetched automatically with a TTL -- ``catalog
refresh`` is a manual override, not a step you have to remember." The payload is
large and rarely changes, so each read populates
``.cache/catalog/{blueprint}-{provider}.json`` (and sibling files for
blueprints/providers) and reuses it until the TTL expires.
"""

from __future__ import annotations

import json
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

from etsy_listings.clients.printify.models import (
    Blueprint,
    PrintProvider,
    ShippingRates,
    VariantSet,
)
from etsy_listings.clients.printify.protocol import CatalogClient

DEFAULT_TTL = timedelta(days=1)

CACHE_SCHEMA = 2
"""Bump whenever a cached model's shape changes, so entries written by an
older build are ignored rather than decoded into something wrong.

Schema 1 stored a ``VariantSet`` whose print-area placeholders were read from
a top-level key the Printify response does not have -- so every entry recorded
zero print areas, and re-validating one under the fixed models would still
yield zero. The cache is gitignored and fully derivable, so discarding a
generation of it costs one refetch; leaving a poisoned entry in place costs a
day of the bug appearing unfixed."""


class CachedCatalogClient(CatalogClient):
    def __init__(
        self,
        inner: CatalogClient,
        cache_dir: Path,
        *,
        ttl: timedelta = DEFAULT_TTL,
        clock: Any = time.time,  # noqa: ANN401 - injected for deterministic tests
    ) -> None:
        self._inner = inner
        self._cache_dir = cache_dir
        self._ttl_seconds = ttl.total_seconds()
        self._clock = clock

    def _read(self, name: str) -> Any | None:  # noqa: ANN401
        path = self._cache_dir / name
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema") != CACHE_SCHEMA:
            return None
        if self._clock() - payload["fetched_at"] > self._ttl_seconds:
            return None
        return payload["data"]

    def _write(self, name: str, data: Any) -> None:  # noqa: ANN401
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        path = self._cache_dir / name
        payload = {"schema": CACHE_SCHEMA, "fetched_at": self._clock(), "data": data}
        path.write_text(json.dumps(payload), encoding="utf-8")

    def blueprints(self) -> list[Blueprint]:
        cached = self._read("blueprints.json")
        if cached is not None:
            return [Blueprint.model_validate(item) for item in cached]
        blueprints = self._inner.blueprints()
        self._write("blueprints.json", [b.model_dump() for b in blueprints])
        return blueprints

    def print_providers(self, blueprint_id: int) -> list[PrintProvider]:
        name = f"providers-{blueprint_id}.json"
        cached = self._read(name)
        if cached is not None:
            return [PrintProvider.model_validate(item) for item in cached]
        providers = self._inner.print_providers(blueprint_id)
        self._write(name, [p.model_dump() for p in providers])
        return providers

    def variants(self, blueprint_id: int, provider_id: int) -> VariantSet:
        name = f"{blueprint_id}-{provider_id}.json"
        cached = self._read(name)
        if cached is not None:
            return VariantSet.model_validate(cached)
        variant_set = self._inner.variants(blueprint_id, provider_id)
        self._write(name, variant_set.model_dump())
        return variant_set

    def shipping(self, blueprint_id: int, provider_id: int) -> ShippingRates:
        name = f"shipping-{blueprint_id}-{provider_id}.json"
        cached = self._read(name)
        if cached is not None:
            return ShippingRates.model_validate(cached)
        rates = self._inner.shipping(blueprint_id, provider_id)
        self._write(name, rates.model_dump())
        return rates

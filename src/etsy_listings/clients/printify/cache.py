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
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

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


_BLUEPRINTS = TypeAdapter(list[Blueprint])
_PROVIDERS = TypeAdapter(list[PrintProvider])
_VARIANTS = TypeAdapter(VariantSet)
_SHIPPING = TypeAdapter(ShippingRates)
"""One adapter per cached shape, built once at import: constructing a
``TypeAdapter`` compiles a validator, and doing that per cache hit would cost
more than the read it is wrapping."""


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

    def _cached[T](self, name: str, adapter: TypeAdapter[T], fetch: Callable[[], T]) -> T:
        """``fetch()``, unless ``name`` already holds a live answer.

        The four methods below differed only in a filename and in how their
        payload was decoded and encoded -- and two of them needed a
        comprehension in each direction purely because they return a ``list``
        of models rather than a model. A ``TypeAdapter`` does not care which:
        it is the same tool ``render.config`` already uses to parse a union
        the plain model API cannot express.
        """
        cached = self._read(name)
        if cached is not None:
            return adapter.validate_python(cached)
        value = fetch()
        self._write(name, adapter.dump_python(value, mode="json"))
        return value

    def blueprints(self) -> list[Blueprint]:
        return self._cached("blueprints.json", _BLUEPRINTS, self._inner.blueprints)

    def print_providers(self, blueprint_id: int) -> list[PrintProvider]:
        return self._cached(
            f"providers-{blueprint_id}.json",
            _PROVIDERS,
            lambda: self._inner.print_providers(blueprint_id),
        )

    def variants(self, blueprint_id: int, provider_id: int) -> VariantSet:
        return self._cached(
            f"{blueprint_id}-{provider_id}.json",
            _VARIANTS,
            lambda: self._inner.variants(blueprint_id, provider_id),
        )

    def shipping(self, blueprint_id: int, provider_id: int) -> ShippingRates:
        return self._cached(
            f"shipping-{blueprint_id}-{provider_id}.json",
            _SHIPPING,
            lambda: self._inner.shipping(blueprint_id, provider_id),
        )

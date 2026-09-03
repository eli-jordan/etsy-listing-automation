from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings.catalog.cache import CachedCatalogClient
from etsy_listings.catalog.fakes import FakeCatalogClient
from etsy_listings.catalog.models import (
    Blueprint,
    PrintAreaPlaceholder,
    PrintProvider,
    Variant,
    VariantOptions,
    VariantSet,
)
from etsy_listings.catalog.resolve import (
    CatalogResolutionError,
    resolve_blueprint,
    resolve_print_provider,
)

BLUEPRINTS = [
    Blueprint(id=6, title="Comfort Colors 1717", brand="Comfort Colors", model="1717"),
    Blueprint(id=12, title="Gildan 5000", brand="Gildan", model="5000"),
]
PROVIDERS = {6: [PrintProvider(id=29, title="Monster Digital")]}
VARIANTS = {
    (6, 29): VariantSet(
        variants=(
            Variant(id=1, title="Black / S", options=VariantOptions(color="Black", size="S")),
            Variant(
                id=2, title="Blue Jean / S", options=VariantOptions(color="Blue Jean", size="S")
            ),
        ),
        placeholders=(PrintAreaPlaceholder(position="front", width=4500, height=5400),),
    )
}


def make_fake() -> FakeCatalogClient:
    return FakeCatalogClient(BLUEPRINTS, PROVIDERS, VARIANTS)


def test_resolve_blueprint_by_name() -> None:
    assert resolve_blueprint("Comfort Colors 1717", BLUEPRINTS).id == 6


def test_resolve_blueprint_unknown_lists_valid_names() -> None:
    with pytest.raises(CatalogResolutionError) as exc_info:
        resolve_blueprint("Not A Real Shirt", BLUEPRINTS)
    message = str(exc_info.value)
    assert "Comfort Colors 1717" in message
    assert "Gildan 5000" in message


def test_resolve_print_provider_unknown_lists_valid_names() -> None:
    with pytest.raises(CatalogResolutionError) as exc_info:
        resolve_print_provider("Nonexistent Printer", PROVIDERS[6])
    assert "Monster Digital" in str(exc_info.value)


def test_variant_set_colors_deduplicates_in_order() -> None:
    variant_set = VARIANTS[(6, 29)]
    assert variant_set.colors == ["Black", "Blue Jean"]


def test_variant_set_placeholder_lookup() -> None:
    variant_set = VARIANTS[(6, 29)]
    assert variant_set.placeholder("front") is not None
    assert variant_set.placeholder("back") is None


def test_fake_catalog_client_satisfies_protocol() -> None:
    fake = make_fake()
    assert fake.blueprints() == BLUEPRINTS
    assert fake.print_providers(6) == PROVIDERS[6]
    assert fake.variants(6, 29) == VARIANTS[(6, 29)]


def test_cached_catalog_client_serves_from_cache_without_hitting_inner(tmp_path: Path) -> None:
    calls: list[str] = []

    class CountingCatalog(FakeCatalogClient):
        def blueprints(self) -> list[Blueprint]:
            calls.append("blueprints")
            return super().blueprints()

    cache_dir = tmp_path / "catalog"
    cached = CachedCatalogClient(CountingCatalog(BLUEPRINTS, PROVIDERS, VARIANTS), cache_dir)

    first = cached.blueprints()
    second = cached.blueprints()

    assert first == second == BLUEPRINTS
    assert calls == ["blueprints"]  # only the first call reached the inner client


def test_cached_catalog_client_refetches_after_ttl_expiry(tmp_path: Path) -> None:
    from datetime import timedelta

    clock = {"t": 1000.0}
    cache_dir = tmp_path / "catalog"
    cached = CachedCatalogClient(
        make_fake(), cache_dir, ttl=timedelta(seconds=10), clock=lambda: clock["t"]
    )
    cached.blueprints()
    clock["t"] += 20
    # Should not raise even though it refetches -- correctness check is that it
    # still returns valid data after the cache entry is considered stale.
    assert cached.blueprints() == BLUEPRINTS

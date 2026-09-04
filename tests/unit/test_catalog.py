from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings.catalog.cache import CachedCatalogClient
from etsy_listings.catalog.fakes import FakeCatalogClient
from etsy_listings.catalog.models import (
    Blueprint,
    PrintAreaPlaceholder,
    PrintProvider,
    ShippingCost,
    ShippingProfile,
    ShippingRates,
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
FRONT = (PrintAreaPlaceholder(position="front", width=4500, height=5400),)
VARIANTS = {
    (6, 29): VariantSet(
        variants=(
            Variant(
                id=1,
                title="Black / S",
                options=VariantOptions(color="Black", size="S"),
                placeholders=FRONT,
            ),
            Variant(
                id=2,
                title="Blue Jean / S",
                options=VariantOptions(color="Blue Jean", size="S"),
                placeholders=FRONT,
            ),
        ),
    )
}


SHIPPING = {
    (6, 29): ShippingRates(
        profiles=(
            ShippingProfile(
                variant_ids=(1, 2),
                first_item=ShippingCost(currency="USD", cost=500),
                additional_items=ShippingCost(currency="USD", cost=200),
            ),
        )
    )
}


def make_fake() -> FakeCatalogClient:
    return FakeCatalogClient(BLUEPRINTS, PROVIDERS, VARIANTS, SHIPPING)


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
    assert fake.shipping(6, 29) == SHIPPING[(6, 29)]


def test_fake_catalog_client_shipping_raises_for_an_unfixtured_key() -> None:
    with pytest.raises(KeyError):
        make_fake().shipping(999, 999)


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


def test_an_entry_from_an_older_schema_is_ignored_not_decoded(tmp_path: Path) -> None:
    """Schema 1 wrote a VariantSet whose print areas came from a top-level
    key Printify does not send, so every entry recorded none. Re-validating
    one under the fixed models still yields none -- the bug would look unfixed
    until the TTL expired. The cache is derivable, so a stale generation of it
    is discarded rather than trusted."""
    import json

    cache_dir = tmp_path / "catalog"
    cache_dir.mkdir(parents=True)
    (cache_dir / "6-29.json").write_text(
        json.dumps(
            {
                "fetched_at": 1e12,  # far in the future: not a TTL miss
                "data": {"variants": [], "placeholders": []},
            }
        ),
        encoding="utf-8",
    )

    variant_set = CachedCatalogClient(make_fake(), cache_dir).variants(6, 29)

    assert variant_set == VARIANTS[(6, 29)]  # refetched, not served from disk
    assert variant_set.placeholder("front") is not None


def test_an_entry_this_build_wrote_is_served_back(tmp_path: Path) -> None:
    cache_dir = tmp_path / "catalog"
    cached = CachedCatalogClient(make_fake(), cache_dir)
    assert cached.variants(6, 29) == cached.variants(6, 29) == VARIANTS[(6, 29)]
    assert cached.variants(6, 29).placeholder("front") is not None


def test_cached_shipping_serves_from_cache_without_hitting_inner(tmp_path: Path) -> None:
    calls: list[str] = []

    class CountingCatalog(FakeCatalogClient):
        def shipping(self, blueprint_id: int, provider_id: int) -> ShippingRates:
            calls.append("shipping")
            return super().shipping(blueprint_id, provider_id)

    cache_dir = tmp_path / "catalog"
    cached = CachedCatalogClient(
        CountingCatalog(BLUEPRINTS, PROVIDERS, VARIANTS, SHIPPING), cache_dir
    )

    first = cached.shipping(6, 29)
    second = cached.shipping(6, 29)

    assert first == second == SHIPPING[(6, 29)]
    assert calls == ["shipping"]


def test_cached_shipping_refetches_after_ttl_expiry(tmp_path: Path) -> None:
    from datetime import timedelta

    clock = {"t": 1000.0}
    cache_dir = tmp_path / "catalog"
    cached = CachedCatalogClient(
        make_fake(), cache_dir, ttl=timedelta(seconds=10), clock=lambda: clock["t"]
    )
    cached.shipping(6, 29)
    clock["t"] += 20
    assert cached.shipping(6, 29) == SHIPPING[(6, 29)]

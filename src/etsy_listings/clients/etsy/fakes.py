"""In-memory Etsy, for the behaviour layer (A4).

Behaviour tests drive this; contract tests drive the HTTP client through
`httpx`'s mock transport against transcripts. Asking either to do the other's
job is the mistake that split exists to prevent.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, NamedTuple

import httpx

from etsy_listings.clients.etsy.models import (
    Inventory,
    Listing,
    ListingImage,
    MarketCandidate,
    MarketListing,
    ProductionPartner,
    ReturnPolicy,
    ShippingProfile,
    Shop,
    ShopSection,
    VariationImageLink,
)
from etsy_listings.clients.etsy.transport import EtsyApiError


class FakeEtsyShopClient:
    """Every read `setup` makes, answered from a dict.

    `find_shops` matches case-insensitively on the whole name rather than as a
    substring: what it stands in for is Etsy's own search, and the caller's
    job is to decide whether a result really is the shop it asked about.
    """

    def __init__(
        self,
        shops: list[Shop] | None = None,
        *,
        owned: Shop | None = None,
        sections: list[ShopSection] | None = None,
        policies: list[ReturnPolicy] | None = None,
    ) -> None:
        self._shops = list(shops or [])
        self._owned = owned
        self._sections = list(sections or [])
        self._policies = list(policies or [])
        self.searched: list[str] = []
        self.owner_lookups: list[int] = []
        self.section_calls = 0
        self.return_policy_calls = 0

    def find_shops(self, name: str) -> list[Shop]:
        self.searched.append(name)
        return [shop for shop in self._shops if shop.shop_name.lower() == name.lower()]

    def shop_by_owner(self, user_id: int) -> Shop | None:
        self.owner_lookups.append(user_id)
        return self._owned

    def shop_sections(self, shop_id: int) -> list[ShopSection]:
        self.section_calls += 1
        return list(self._sections)

    def return_policies(self, shop_id: int) -> list[ReturnPolicy]:
        self.return_policy_calls += 1
        return list(self._policies)


class FakeEtsyListingClient:
    """Models the two measured API quirks a tidy fake would hide: `image_ids`
    as a full-replacement set that detaches whatever it omits, and
    `overwrite: true` replacing an image in place -- a new id at the same
    rank, everything else untouched -- rather than colliding with what was
    there (phase-3-etsy.md decision 5).
    """

    def __init__(
        self,
        *,
        shipping_profiles: list[ShippingProfile] | None = None,
        production_partners: list[ProductionPartner] | None = None,
        sections: list[ShopSection] | None = None,
        policies: list[ReturnPolicy] | None = None,
    ) -> None:
        self._listings: dict[int, Listing] = {}
        self._images: dict[int, list[ListingImage]] = {}
        self._inventory: dict[int, Inventory] = {}
        self._variation_images: dict[int, list[VariationImageLink]] = {}
        self._shipping_profiles = list(shipping_profiles or [])
        self._production_partners = list(production_partners or [])
        self._sections = list(sections or [])
        self._policies = list(policies or [])
        self._next_image_id = 0
        self.updated: list[dict[str, Any]] = []
        self.uploads: list[bytes] = []
        """Every upload's bytes, in call order -- what a test checks to prove
        a re-run did *not* resend an image whose content did not change."""
        self.shipping_profile_calls = 0
        self.production_partner_calls = 0
        self.section_calls = 0
        self.return_policy_calls = 0

    def seed_listing(self, listing_id: int, *, shop_id: int | None = None, **fields: Any) -> None:
        self._listings[listing_id] = Listing(listing_id=listing_id, shop_id=shop_id, **fields)
        self._images.setdefault(listing_id, [])

    def seed_inventory(self, listing_id: int, inventory: Inventory) -> None:
        self._inventory[listing_id] = inventory

    # -------------------------------------------------------------- reads

    def get_listing(self, listing_id: int, *, include_images: bool = False) -> Listing | None:
        listing = self._listings.get(listing_id)
        if listing is None:
            return None
        images = tuple(self._images.get(listing_id, [])) if include_images else ()
        return listing.model_copy(update={"images": images})

    def listing_states(self, listing_ids: Sequence[int]) -> dict[int, str]:
        """Only the ids this fake has actually been seeded with, and only
        those carrying a state -- the real batch read omits both, and a caller
        that treats "absent" as "draft" should fail here rather than in
        production."""
        states: dict[int, str] = {}
        for listing_id in listing_ids:
            listing = self._listings.get(listing_id)
            if listing is not None and listing.state is not None:
                states[listing_id] = listing.state
        return states

    def get_listing_inventory(self, listing_id: int) -> Inventory:
        return self._inventory.get(listing_id, Inventory())

    def get_listing_variation_images(
        self, shop_id: int, listing_id: int
    ) -> list[VariationImageLink]:
        return list(self._variation_images.get(listing_id, []))

    def shipping_profiles(self, shop_id: int) -> list[ShippingProfile]:
        self.shipping_profile_calls += 1
        return list(self._shipping_profiles)

    def production_partners(self, shop_id: int) -> list[ProductionPartner]:
        self.production_partner_calls += 1
        return list(self._production_partners)

    def shop_sections(self, shop_id: int) -> list[ShopSection]:
        self.section_calls += 1
        return list(self._sections)

    def return_policies(self, shop_id: int) -> list[ReturnPolicy]:
        self.return_policy_calls += 1
        return list(self._policies)

    # ------------------------------------------------------------- writes

    def update_listing(self, shop_id: int, listing_id: int, patch: dict[str, Any]) -> Listing:
        self.updated.append(dict(patch))
        image_ids = patch.get("image_ids")
        if image_ids is not None:
            by_id = {image.listing_image_id: image for image in self._images.get(listing_id, [])}
            self._images[listing_id] = [by_id[i] for i in image_ids if i in by_id]
        fields = {
            key: value
            for key, value in patch.items()
            if key != "image_ids" and key in Listing.model_fields
        }
        self._listings[listing_id] = self._listings[listing_id].model_copy(update=fields)
        return self._listings[listing_id].model_copy(update={"images": ()})

    def upload_listing_image(
        self,
        shop_id: int,
        listing_id: int,
        *,
        file_name: str,
        contents: bytes,
        rank: int,
        alt_text: str = "",
        overwrite: bool = False,
        listing_image_id: int | None = None,
    ) -> ListingImage:
        self.uploads.append(contents)
        self._next_image_id += 1
        image = ListingImage(
            listing_image_id=self._next_image_id,
            rank=rank,
            alt_text=alt_text,
            url_570xN=f"https://fake-etsy.test/{self._next_image_id}_570xN.jpg",
        )
        images = self._images.setdefault(listing_id, [])
        if overwrite and listing_image_id is not None:
            for index, existing in enumerate(images):
                if existing.listing_image_id == listing_image_id:
                    images[index] = image
                    return image
        images.append(image)
        return image

    def update_variation_images(
        self, shop_id: int, listing_id: int, links: list[VariationImageLink]
    ) -> None:
        self._variation_images[listing_id] = list(links)


# ------------------------------------------------------------------ market

MarketMethod = Literal["search_active", "listings_by_ids", "review_count"]

MARKET_BATCH_LIMIT = 100
"""The real batch's chunk size, so the fake's call log counts as it does."""


class MarketCall(NamedTuple):
    """One call the fake answered or refused: the method, and what it asked
    -- the query, the chunk of ids as a tuple, or the listing id."""

    method: MarketMethod
    argument: object


def market_listing(listing_id: int, **fields: Any) -> MarketListing:
    """A listing with plausible defaults, for seeding. ``shop_id`` defaults to
    one shop per listing; override any field by name."""
    defaults: dict[str, Any] = {
        "shop_id": 1000 + listing_id,
        "title": f"Listing {listing_id}",
        "url": f"https://www.etsy.test/listing/{listing_id}",
        "original_creation_timestamp": 1_700_000_000,
    }
    return MarketListing(listing_id=listing_id, **(defaults | fields))


def rate_limited() -> EtsyApiError:
    """What the real client raises once a 429 has outlasted the retries."""
    return EtsyApiError(429, error="You have exceeded your quota")


def server_error(status: int = 503) -> EtsyApiError:
    """What the real client raises once a 5xx has outlasted the retries."""
    return EtsyApiError(status, error="upstream unavailable")


def network_error() -> httpx.TransportError:
    """What the real client lets through once a dropped connection has
    outlasted the retries: the transport error itself, not a wrapper."""
    return httpx.ConnectError("connection reset by peer")


@dataclass
class _Failure:
    method: MarketMethod
    error: Exception
    times: int
    argument: object | None


class FakeEtsyMarketClient:
    """The Etsy market, answered from what a test seeded.

    Listings are seeded once with everything the batch returns; a search
    answers the seeded ids in the order given, narrowed to the candidate
    fields a real search carries. Every call -- failed ones included, since
    they cost quota too -- lands in :attr:`calls`, the batch once per chunk
    of a hundred as the real one is. Failures are injected as what the real
    client raises *after* its retries, since the retries are the transport's
    and are tested there. Thread-safe: research calls it from five threads.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._listings: dict[int, MarketListing] = {}
        self._reviews: dict[int, int] = {}
        self._searches: dict[str, list[int]] = {}
        self._failures: list[_Failure] = []
        self.calls: list[MarketCall] = []

    # ----------------------------------------------------------- seeding

    def seed_listing(self, listing: MarketListing, *, reviews: int = 0) -> None:
        with self._lock:
            self._listings[listing.listing_id] = listing
            self._reviews[listing.listing_id] = reviews

    def seed_search(self, query: str, listing_ids: Sequence[int]) -> None:
        """What ``query`` finds, best-ranked first. Every id must be seeded
        with :meth:`seed_listing`, before or after."""
        with self._lock:
            self._searches[query] = list(listing_ids)

    def fail(
        self,
        method: MarketMethod,
        error: Exception,
        *,
        times: int = 1,
        argument: object | None = None,
    ) -> None:
        """Make the next ``times`` calls to ``method`` raise ``error`` --
        only those asking about ``argument``, when one is given."""
        with self._lock:
            self._failures.append(_Failure(method, error, times, argument))

    def count(self, method: MarketMethod) -> int:
        with self._lock:
            return sum(1 for call in self.calls if call.method == method)

    # ----------------------------------------------------------- the calls

    def search_active(self, query: str, *, limit: int = 25) -> list[MarketCandidate]:
        self._record("search_active", query)
        with self._lock:
            ids = self._searches.get(query, [])[:limit]
            return [
                MarketCandidate.model_validate(
                    self._listings[i].model_dump(include=set(MarketCandidate.model_fields))
                )
                for i in ids
            ]

    def listings_by_ids(self, ids: Sequence[int]) -> list[MarketListing]:
        wanted = list(ids)
        found: list[MarketListing] = []
        for start in range(0, len(wanted), MARKET_BATCH_LIMIT):
            chunk = tuple(wanted[start : start + MARKET_BATCH_LIMIT])
            self._record("listings_by_ids", chunk)
            with self._lock:
                found.extend(self._listings[i] for i in chunk if i in self._listings)
        return found

    def review_count(self, listing_id: int) -> int:
        self._record("review_count", listing_id)
        with self._lock:
            return self._reviews.get(listing_id, 0)

    def _record(self, method: MarketMethod, argument: object) -> None:
        with self._lock:
            self.calls.append(MarketCall(method, argument))
            for failure in self._failures:
                if failure.method != method or failure.times <= 0:
                    continue
                if failure.argument is not None and failure.argument != argument:
                    continue
                failure.times -= 1
                raise failure.error

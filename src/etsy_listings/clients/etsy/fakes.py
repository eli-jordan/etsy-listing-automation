"""In-memory Etsy, for the behaviour layer (A4).

Behaviour tests drive this; contract tests drive the HTTP client through
`httpx`'s mock transport against transcripts. Asking either to do the other's
job is the mistake that split exists to prevent.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal, NamedTuple

import httpx

from etsy_listings.clients.etsy.listings import (
    DAILY_VIDEO_ASSOCIATIONS,
    VIDEO_SLOTS,
    VideoBudgetExhaustedError,
    VideoSlotsFullError,
    video_content_type,
)
from etsy_listings.clients.etsy.models import (
    ALREADY_DECODED,
    Inventory,
    Listing,
    ListingImage,
    ListingVideo,
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


@dataclass(frozen=True)
class GallerySlot:
    """One position in a listing's gallery, as Shop Manager shows it."""

    kind: Literal["image", "video"]
    id: int


@dataclass
class _Attached:
    """A video on a listing: when it was attached, and how many images the
    listing had then -- the two facts decision 9 found its position hangs on.
    """

    video_id: int
    state: str
    attached: int
    """A sequence number, not a time: "attached longest" is an order."""
    anchor: int


DAY_SECONDS = 24 * 60 * 60


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
    """Models the measured API quirks a tidy fake would hide: `image_ids`
    as a full-replacement set that detaches whatever it omits, and
    `overwrite: true` replacing an image in place -- a new id at the same
    rank, everything else untouched -- rather than colliding with what was
    there (phase-3-etsy.md decision 5).

    And the video gallery of decision 9, which behaviour tests can only see
    through :meth:`gallery`: the video attached longest is featured at
    position 2, any other is anchored after the number of images the listing
    had when it was attached, and deleting the featured one promotes the
    other. The listing's limits are enforced as Etsy enforces them -- two
    active videos, ten associations per listing per 24 hours on ``clock`` --
    and detaching an image through `image_ids` deletes its swatch link.

    Where decision 9 measured nothing, the fake refuses with a
    :class:`ValueError` naming the gap rather than guessing, so a stage that
    comes to depend on unmeasured behaviour finds out in a test.
    """

    def __init__(
        self,
        *,
        shipping_profiles: list[ShippingProfile] | None = None,
        production_partners: list[ProductionPartner] | None = None,
        sections: list[ShopSection] | None = None,
        policies: list[ReturnPolicy] | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._clock = clock
        self._listings: dict[int, Listing] = {}
        self._images: dict[int, list[ListingImage]] = {}
        self._known_images: dict[int, dict[int, ListingImage]] = {}
        """Every image a listing has ever had, attached or not."""
        self._inventory: dict[int, Inventory] = {}
        self._variation_images: dict[int, list[VariationImageLink]] = {}
        self._shipping_profiles = list(shipping_profiles or [])
        self._production_partners = list(production_partners or [])
        self._sections = list(sections or [])
        self._policies = list(policies or [])
        self._next_image_id = 0
        self._shop_videos: dict[int, ListingVideo] = {}
        """Every video the shop has, in upload order. Etsy keeps a deleted
        video's file, which is what makes re-attaching by id possible."""
        self._videos: dict[int, list[_Attached]] = {}
        self._associations: dict[int, list[float]] = {}
        self._next_video_id = 844256000
        self._next_attach = 0
        self.video_uploads: list[bytes] = []
        """Every video upload's bytes -- what proves a move re-attached by id
        rather than re-sending the file."""
        self.video_attaches: list[int] = []
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

    def seed_video(self, listing_id: int, *, video_state: str = "active") -> ListingVideo:
        """A video already on the listing, placed as an attach now would be
        but without spending the day's budget: a seller's own from Shop
        Manager, or -- ``inactive`` -- one a legacy-mode upload switched off,
        which the tool itself never causes (decision 9)."""
        video = self._new_video()
        attached = self._attach(listing_id, video.video_id)
        self._videos[listing_id][-1].state = video_state
        return attached.model_copy(update={"video_state": video_state})

    def seed_inventory(self, listing_id: int, inventory: Inventory) -> None:
        self._inventory[listing_id] = inventory

    # -------------------------------------------------------------- reads

    def get_listing(
        self, listing_id: int, *, include_images: bool = False, include_videos: bool = False
    ) -> Listing | None:
        listing = self._listings.get(listing_id)
        if listing is None:
            return None
        images = tuple(self._images.get(listing_id, [])) if include_images else ()
        videos = self._listed_videos(listing_id) if include_videos else ()
        return listing.model_copy(update={"images": images, "videos": videos})

    def _listed_videos(self, listing_id: int) -> tuple[ListingVideo, ...]:
        """Newest *upload* first, inactive ones included -- the response's
        order, measured, and nothing to do with the gallery's."""
        upload_order = list(self._shop_videos)
        on_listing = sorted(
            self._videos.get(listing_id, []),
            key=lambda a: upload_order.index(a.video_id),
            reverse=True,
        )
        return tuple(
            self._shop_videos[a.video_id].model_copy(update={"video_state": a.state})
            for a in on_listing
        )

    def gallery(self, listing_id: int) -> tuple[GallerySlot, ...]:
        """The listing's gallery as Shop Manager would show it (decision 9).

        Read-only, and for tests: the real API has no such read, which is
        exactly why the fake has to model one. Inactive videos do not show,
        and neither does any video on a listing with no images: Etsy will not
        publish one, and what Shop Manager shows then was not measured.
        """
        images = self._images.get(listing_id, [])
        active = sorted(
            (a for a in self._videos.get(listing_id, []) if a.state == "active"),
            key=lambda a: a.attached,
        )
        featured, others = active[:1], active[1:]
        slots: list[GallerySlot] = []
        for count, image in enumerate(images, start=1):
            slots.append(GallerySlot("image", image.listing_image_id))
            if count == 1:
                slots.extend(GallerySlot("video", a.video_id) for a in featured)
            slots.extend(
                GallerySlot("video", a.video_id)
                for a in others
                if max(1, min(a.anchor, len(images))) == count
            )
        return tuple(slots)

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
            self._set_image_ids(listing_id, list(image_ids))
        fields = {
            key: value
            for key, value in patch.items()
            if key != "image_ids" and key in Listing.model_fields
        }
        self._listings[listing_id] = self._listings[listing_id].model_copy(update=fields)
        return self._listings[listing_id].model_copy(update={"images": ()})

    def _set_image_ids(self, listing_id: int, image_ids: list[int]) -> None:
        """Etsy keeps a detached image, so a later `image_ids` can bring it
        back (decision 9's cut-and-restore) -- but not its swatch link, which
        detaching deletes for good (measured). An id that is no image of this
        listing, such as a video's, is refused whole (measured)."""
        known = self._known_images.setdefault(listing_id, {})
        if any(image_id not in known for image_id in image_ids):
            raise EtsyApiError(
                400, error="There was a problem with /images : That ListingImage does not exist."
            )
        kept = set(image_ids)
        self._variation_images[listing_id] = [
            link for link in self._variation_images.get(listing_id, []) if link.image_id in kept
        ]
        self._images[listing_id] = [known[image_id] for image_id in image_ids]

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
        self._known_images.setdefault(listing_id, {})[image.listing_image_id] = image
        images = self._images.setdefault(listing_id, [])
        if overwrite and listing_image_id is not None:
            for index, existing in enumerate(images):
                if existing.listing_image_id == listing_image_id:
                    images[index] = image
                    return image
        images.append(image)
        return image

    def upload_listing_video(
        self, shop_id: int, listing_id: int, *, file_name: str, contents: bytes
    ) -> ListingVideo:
        video_content_type(file_name)
        self._admit_video(listing_id)
        self.video_uploads.append(contents)
        return self._attach(listing_id, self._new_video().video_id)

    def _new_video(self) -> ListingVideo:
        self._next_video_id += 1
        video = ListingVideo(
            video_id=self._next_video_id,
            video_state="active",
            width=1440,
            height=1440,
            video_url=f"https://fake-etsy.test/videos/{self._next_video_id}/vid_v1.mp4",
            thumbnail_url=(
                f"https://fake-etsy.test/videos/{self._next_video_id}/listing_thumbnail_v1.jpg"
            ),
        )
        self._shop_videos[video.video_id] = video
        return video

    def attach_listing_video(self, shop_id: int, listing_id: int, video_id: int) -> ListingVideo:
        """Re-attach a video the shop already has. One `inactive` on this
        listing is reactivated (measured); either way it is anchored afresh
        and counts against the budget, as a fresh upload does."""
        if video_id not in self._shop_videos:
            raise ValueError(f"unmeasured: attaching video {video_id}, which this shop never had")
        attached = self._videos.get(listing_id, [])
        if any(a.video_id == video_id and a.state == "active" for a in attached):
            raise ValueError(f"unmeasured: attaching video {video_id}, already active here")
        self._admit_video(listing_id)
        self.video_attaches.append(video_id)
        self._videos[listing_id] = [a for a in attached if a.video_id != video_id]
        return self._attach(listing_id, video_id)

    def delete_listing_video(self, shop_id: int, listing_id: int, video_id: int) -> None:
        """Off the listing, `active` or `inactive`; the file stays the shop's."""
        attached = self._videos.get(listing_id, [])
        if not any(a.video_id == video_id for a in attached):
            raise ValueError(f"unmeasured: deleting video {video_id}, which is not on the listing")
        self._videos[listing_id] = [a for a in attached if a.video_id != video_id]

    def _admit_video(self, listing_id: int) -> None:
        """Etsy's two refusals, in the order the fake checks them: a full
        listing first, then the day's budget. Which Etsy checks first was not
        measured; a refused attempt is not counted against the budget."""
        attached = self._videos.get(listing_id, [])
        if sum(a.state == "active" for a in attached) >= VIDEO_SLOTS:
            raise VideoSlotsFullError()
        now = self._clock()
        recent = [t for t in self._associations.get(listing_id, []) if now - t < DAY_SECONDS]
        if len(recent) >= DAILY_VIDEO_ASSOCIATIONS:
            raise VideoBudgetExhaustedError()
        self._associations[listing_id] = [*recent, now]

    def _attach(self, listing_id: int, video_id: int) -> ListingVideo:
        self._next_attach += 1
        self._videos.setdefault(listing_id, []).append(
            _Attached(
                video_id=video_id,
                state="active",
                attached=self._next_attach,
                anchor=len(self._images.get(listing_id, [])),
            )
        )
        return self._shop_videos[video_id].model_copy(update={"video_state": "active"})

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
                    self._listings[i].model_dump(include=set(MarketCandidate.model_fields)),
                    context=ALREADY_DECODED,
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

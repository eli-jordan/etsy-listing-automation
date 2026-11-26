"""The signed-in Etsy surface: listing writes and shop-section creation."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any, Protocol

from etsy_listings.core.clients.etsy.models import (
    Inventory,
    Listing,
    ListingImage,
    ListingVideo,
    ProductionPartner,
    ReturnPolicy,
    ShippingProfile,
    ShopSection,
    VariationImageLink,
)
from etsy_listings.core.clients.etsy.shops import ShopMetadataReads
from etsy_listings.core.clients.etsy.transport import (
    HTTP_NOT_FOUND,
    EtsyApiError,
    Transport,
    results_of,
)

HTTP_BAD_REQUEST = 400
HTTP_CONFLICT = 409

MAX_VIDEOS_TEXT = "The listing already has the maximum number of videos allowed."
"""Etsy's words for **two** different refusals (decision 9, measured): a
`409` when two videos are already active, and a `400` when the listing has
spent its ten associations for the day -- on a listing holding none."""

VIDEO_SLOTS = 2
DAILY_VIDEO_ASSOCIATIONS = 10


class VideoSlotsFullError(EtsyApiError):
    def __init__(self, status_code: int = HTTP_CONFLICT, *, error: str = MAX_VIDEOS_TEXT) -> None:
        super().__init__(
            status_code,
            error=error,
            message=(
                f"Etsy refused the video ({status_code}): the listing already has "
                f"{VIDEO_SLOTS} active videos, the most it can hold."
            ),
        )


class VideoBudgetExhaustedError(EtsyApiError):
    def __init__(
        self, status_code: int = HTTP_BAD_REQUEST, *, error: str = MAX_VIDEOS_TEXT
    ) -> None:
        super().__init__(
            status_code,
            error=error,
            message=(
                f"Etsy refused the video ({status_code}): Etsy allows "
                f"{DAILY_VIDEO_ASSOCIATIONS} video uploads or re-attaches per listing in "
                f"24 hours, and this listing has used them. Etsy words this as "
                f'"{error}" whatever the listing holds. Re-run tomorrow.'
            ),
        )


def _video_refusal(exc: EtsyApiError) -> EtsyApiError:
    if exc.status_code == HTTP_CONFLICT:
        return VideoSlotsFullError(exc.status_code, error=exc.error)
    if exc.status_code == HTTP_BAD_REQUEST and "maximum number of videos" in exc.error:
        return VideoBudgetExhaustedError(exc.status_code, error=exc.error)
    return exc


VIDEO_CONTENT_TYPES = {".mp4": "video/mp4", ".mov": "video/quicktime"}
"""ADR-0045's two video types -- of Etsy's seven, the two a browser previews --
and the content type each is sent as."""

MULTI_VIDEO = {"is_multi_video": "true"}
"""On every upload and every attach. Without it Etsy's legacy mode makes
every other video on the listing `inactive` (decision 9, measured)."""

BATCH_LIMIT = 100
"""Etsy's documented ceiling on `getListingsByListingIds`. Chunking is this
module's job rather than the caller's -- a workspace with 150 listings is not
a different question from one with five."""


@dataclass(frozen=True)
class ImageUpload:
    file_name: str
    contents: bytes
    rank: int
    alt_text: str = ""
    overwrite: bool = False
    listing_image_id: int | None = None


class EtsyListingClient(Protocol):
    def get_listing(
        self, listing_id: int, *, include_images: bool = False, include_videos: bool = False
    ) -> Listing | None: ...

    def listing_states(self, listing_ids: Sequence[int]) -> dict[int, str]: ...

    def update_listing(self, shop_id: int, listing_id: int, patch: dict[str, Any]) -> Listing: ...

    def upload_listing_image(
        self, shop_id: int, listing_id: int, upload: ImageUpload
    ) -> ListingImage: ...

    def upload_listing_video(
        self, shop_id: int, listing_id: int, *, file_name: str, contents: bytes
    ) -> ListingVideo: ...

    def attach_listing_video(
        self, shop_id: int, listing_id: int, video_id: int
    ) -> ListingVideo: ...

    def delete_listing_video(self, shop_id: int, listing_id: int, video_id: int) -> None: ...

    def get_listing_inventory(self, listing_id: int) -> Inventory: ...

    def update_variation_images(
        self, shop_id: int, listing_id: int, links: list[VariationImageLink]
    ) -> None: ...

    def get_listing_variation_images(
        self, shop_id: int, listing_id: int
    ) -> list[VariationImageLink]: ...

    def shipping_profiles(self, shop_id: int) -> list[ShippingProfile]: ...

    def production_partners(self, shop_id: int) -> list[ProductionPartner]: ...

    def shop_sections(self, shop_id: int) -> list[ShopSection]: ...

    def return_policies(self, shop_id: int) -> list[ReturnPolicy]: ...

    def create_shop_section(self, shop_id: int, title: str) -> ShopSection: ...


class HttpEtsyListingClient(ShopMetadataReads):
    def __init__(self, transport: Transport) -> None:
        self._transport = transport

    def get_listing(
        self, listing_id: int, *, include_images: bool = False, include_videos: bool = False
    ) -> Listing | None:
        # One comma-joined `includes`, never the key twice: which of two
        # repeated keys Etsy honours is not something to leave to chance.
        includes = [
            name
            for name, wanted in (("Images", include_images), ("Videos", include_videos))
            if wanted
        ]
        params = {"includes": ",".join(includes)} if includes else None
        try:
            response = self._transport.get(f"/v3/application/listings/{listing_id}", params=params)
        except EtsyApiError as exc:
            if exc.status_code == HTTP_NOT_FOUND:
                return None
            raise
        return Listing.model_validate(response.json())

    def listing_states(self, listing_ids: Sequence[int]) -> dict[int, str]:
        """Each of ``listing_ids``' Etsy-side ``state``, keyed by listing id.

        One request per :data:`BATCH_LIMIT` ids rather than one per listing:
        the caller is the listings UI asking about every listing in the
        workspace at once, and a `getListing` apiece would make opening the
        page cost a round trip per row.

        Unscoped, like `getListing` beside it -- `getListingsByListingIds`
        needs only the app key pair. An id Etsy does not answer for is
        **absent** from the result rather than present with an invented state:
        "we could not find out" and "it is still a draft" are different facts,
        and only the caller knows which way to resolve the difference.
        """
        states: dict[int, str] = {}
        ids = list(listing_ids)
        for start in range(0, len(ids), BATCH_LIMIT):
            chunk = ids[start : start + BATCH_LIMIT]
            response = self._transport.get(
                "/v3/application/listings/batch",
                params={"listing_ids": ",".join(str(i) for i in chunk)},
            )
            for row in results_of(response.json()):
                listing = Listing.model_validate(row)
                if listing.state is not None:
                    states[listing.listing_id] = listing.state
        return states

    def get_listing_inventory(self, listing_id: int) -> Inventory:
        response = self._transport.get(f"/v3/application/listings/{listing_id}/inventory")
        return Inventory.model_validate(response.json())

    def get_listing_variation_images(
        self, shop_id: int, listing_id: int
    ) -> list[VariationImageLink]:
        """Shop-scoped, like the write beside it -- and unlike every other
        *read* in this client, which is why it was got wrong once and worth
        stating: `getListingVariationImages` takes `shop_id` in the path.

        The unscoped `/v3/application/listings/{id}/variation-images` 404s for
        every listing, linked or not, which is indistinguishable from "no
        links yet" and was once read as exactly that. On the correct path a
        listing with no links answers `200` with `count: 0` like every other
        list read here (measured, both shapes), so a `404` means the listing
        is gone and is raised rather than flattened into an empty list.
        """
        response = self._transport.get(
            f"/v3/application/shops/{shop_id}/listings/{listing_id}/variation-images"
        )
        return [VariationImageLink.model_validate(row) for row in results_of(response.json())]

    def shipping_profiles(self, shop_id: int) -> list[ShippingProfile]:
        response = self._transport.get(f"/v3/application/shops/{shop_id}/shipping-profiles")
        return [ShippingProfile.model_validate(row) for row in results_of(response.json())]

    def production_partners(self, shop_id: int) -> list[ProductionPartner]:
        response = self._transport.get(f"/v3/application/shops/{shop_id}/production-partners")
        return [ProductionPartner.model_validate(row) for row in results_of(response.json())]

    def create_shop_section(self, shop_id: int, title: str) -> ShopSection:
        response = self._transport.post(
            f"/v3/application/shops/{shop_id}/sections", data={"title": title}
        )
        return ShopSection.model_validate(response.json())

    def update_listing(self, shop_id: int, listing_id: int, patch: dict[str, Any]) -> Listing:
        body = dict(patch)
        if isinstance(body.get("image_ids"), (list, tuple)):
            # One joined string, never repeated keys (ADR-0031).
            body["image_ids"] = ",".join(str(image_id) for image_id in body["image_ids"])
        response = self._transport.patch(
            f"/v3/application/shops/{shop_id}/listings/{listing_id}", json=body
        )
        return Listing.model_validate(response.json())

    def upload_listing_image(
        self, shop_id: int, listing_id: int, upload: ImageUpload
    ) -> ListingImage:
        """Upload at ``upload.rank``, with its alt text -- there is no
        image-update endpoint, so alt text is only ever set here."""
        file_name, contents, rank = upload.file_name, upload.contents, upload.rank
        alt_text, overwrite = upload.alt_text, upload.overwrite
        listing_image_id = upload.listing_image_id
        data: dict[str, str] = {"rank": str(rank), "alt_text": alt_text}
        if overwrite:
            data["overwrite"] = "true"
        if listing_image_id is not None:
            data["listing_image_id"] = str(listing_image_id)
        response = self._transport.post(
            f"/v3/application/shops/{shop_id}/listings/{listing_id}/images",
            data=data,
            files={"image": (file_name, contents)},
        )
        return ListingImage.model_validate(response.json())

    def upload_listing_video(
        self, shop_id: int, listing_id: int, *, file_name: str, contents: bytes
    ) -> ListingVideo:
        content_type = video_content_type(file_name)
        return self._post_video(
            shop_id,
            listing_id,
            data={"name": file_name},
            files={"video": (file_name, contents, content_type)},
        )

    def attach_listing_video(self, shop_id: int, listing_id: int, video_id: int) -> ListingVideo:
        return self._post_video(shop_id, listing_id, data={"video_id": str(video_id)})

    def _post_video(self, shop_id: int, listing_id: int, **kwargs: Any) -> ListingVideo:
        try:
            response = self._transport.post(
                f"/v3/application/shops/{shop_id}/listings/{listing_id}/videos",
                params=MULTI_VIDEO,
                **kwargs,
            )
        except EtsyApiError as exc:
            refusal = _video_refusal(exc)
            if refusal is exc:
                raise
            raise refusal from exc
        return ListingVideo.model_validate(response.json())

    def delete_listing_video(self, shop_id: int, listing_id: int, video_id: int) -> None:
        self._transport.delete(
            f"/v3/application/shops/{shop_id}/listings/{listing_id}/videos/{video_id}"
        )

    def update_variation_images(
        self, shop_id: int, listing_id: int, links: list[VariationImageLink]
    ) -> None:
        body = {
            "variation_images": [
                {
                    "property_id": link.property_id,
                    "value_id": link.value_id,
                    "image_id": link.image_id,
                }
                for link in links
            ]
        }
        self._transport.post(
            f"/v3/application/shops/{shop_id}/listings/{listing_id}/variation-images", json=body
        )


def video_content_type(file_name: str) -> str:
    """The content type a video upload is sent as, or a :class:`ValueError`
    for a file ADR-0045 does not allow -- raised before a byte is sent, since
    anything else reaching the client is a caller's bug that would spend one
    of the listing's daily associations. The fake shares it, so a stage
    tested against the fake meets the same refusal."""
    suffix = PurePosixPath(file_name).suffix.lower()
    content_type = VIDEO_CONTENT_TYPES.get(suffix)
    if content_type is None:
        raise ValueError(f"{file_name}: a listing video is .mp4 or .mov, not {suffix!r}")
    return content_type

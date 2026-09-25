"""Locks in the video behaviour `FakeEtsyListingClient` has to reproduce,
because the fake's `gallery()` is the only place a behaviour test can see
where a video sits -- the real API never reports it (phase-3-etsy.md
decision 9, "Testing").

The sequence tests replay the recon's labelled probe step for step: images
IMG 1-5 and videos A and B on a throwaway draft, with the gallery each row of
decision 9's "Where a video appears" table records, as read by eye in Shop
Manager on 2026-09-25.
"""

from __future__ import annotations

from etsy_listings.clients.etsy.fakes import FakeEtsyListingClient, GallerySlot

SHOP_ID = 67961328
LISTING_ID = 4582417670


class Probe:
    """The recon's draft: labelled images and videos, and the gallery read
    back in those labels."""

    def __init__(self, client: FakeEtsyListingClient | None = None) -> None:
        self.client = client or FakeEtsyListingClient()
        self.client.seed_listing(LISTING_ID, shop_id=SHOP_ID)
        self.images: dict[str, int] = {}
        self.videos: dict[str, int] = {}

    def image(self, label: str) -> None:
        image = self.client.upload_listing_image(
            SHOP_ID,
            LISTING_ID,
            file_name=f"img{label}.png",
            contents=label.encode(),
            rank=len(self.images) + 1,
        )
        self.images[label] = image.listing_image_id

    def video(self, label: str) -> None:
        video = self.client.upload_listing_video(
            SHOP_ID, LISTING_ID, file_name=f"video-{label}.mp4", contents=label.encode()
        )
        self.videos[label] = video.video_id

    def image_ids(self, *labels: str) -> None:
        self.client.update_listing(
            SHOP_ID, LISTING_ID, {"image_ids": [self.images[label] for label in labels]}
        )

    def delete(self, label: str) -> None:
        self.client.delete_listing_video(SHOP_ID, LISTING_ID, self.videos[label])

    def attach(self, label: str) -> None:
        self.client.attach_listing_video(SHOP_ID, LISTING_ID, self.videos[label])

    def gallery(self) -> list[str]:
        names = {GallerySlot("image", i): label for label, i in self.images.items()}
        names |= {GallerySlot("video", i): label for label, i in self.videos.items()}
        return [names[slot] for slot in self.client.gallery(LISTING_ID)]


def test_an_uploaded_video_is_active_on_the_listing_at_once() -> None:
    probe = Probe()
    probe.image("1")

    probe.video("A")

    listing = probe.client.get_listing(LISTING_ID, include_videos=True)
    assert listing is not None
    assert [(v.video_id, v.video_state) for v in listing.videos] == [(probe.videos["A"], "active")]


def test_videos_are_listed_newest_upload_first() -> None:
    probe = Probe()
    probe.image("1")
    probe.video("A")
    probe.video("B")

    listing = probe.client.get_listing(LISTING_ID, include_videos=True)

    assert listing is not None
    assert [v.video_id for v in listing.videos] == [probe.videos["B"], probe.videos["A"]]


def test_videos_are_absent_unless_asked_for() -> None:
    probe = Probe()
    probe.image("1")
    probe.video("A")

    listing = probe.client.get_listing(LISTING_ID)

    assert listing is not None
    assert listing.videos == ()


def test_the_only_video_is_featured_at_position_two() -> None:
    probe = Probe()
    for label in "123":
        probe.image(label)

    probe.video("A")

    assert probe.gallery() == ["1", "A", "2", "3"]


# ------------------------------------------ decision 9, "Where a video appears"


def _row_1() -> Probe:
    """IMG 1-4, then VIDEO A, then VIDEO B, then IMG 5."""
    probe = Probe()
    for label in "1234":
        probe.image(label)
    probe.video("A")
    probe.video("B")
    probe.image("5")
    return probe


def _row_2() -> Probe:
    """`image_ids` reversed to 5...1."""
    probe = _row_1()
    probe.image_ids("5", "4", "3", "2", "1")
    return probe


def _row_3() -> Probe:
    """B deleted, `image_ids` cut to IMG 5 alone, B re-attached, all five
    restored."""
    probe = _row_2()
    probe.delete("B")
    probe.image_ids("5")
    probe.attach("B")
    probe.image_ids("5", "4", "3", "2", "1")
    return probe


def _row_4() -> Probe:
    """A deleted."""
    probe = _row_3()
    probe.delete("A")
    return probe


def _row_5() -> Probe:
    """A re-attached."""
    probe = _row_4()
    probe.attach("A")
    return probe


def test_row_1_the_second_video_is_anchored_after_the_images_it_found() -> None:
    assert _row_1().gallery() == ["1", "A", "2", "3", "4", "B", "5"]


def test_row_2_reordering_images_leaves_the_second_video_at_its_count() -> None:
    assert _row_2().gallery() == ["5", "A", "4", "3", "2", "B", "1"]


def test_row_3_re_attaching_anchors_afresh() -> None:
    assert _row_3().gallery() == ["5", "A", "B", "4", "3", "2", "1"]


def test_row_4_deleting_the_featured_video_promotes_the_other() -> None:
    assert _row_4().gallery() == ["5", "B", "4", "3", "2", "1"]


def test_row_5_a_re_attached_video_is_no_longer_the_one_attached_longest() -> None:
    assert _row_5().gallery() == ["5", "B", "4", "3", "2", "1", "A"]


def test_a_move_by_re_attaching_sends_no_bytes() -> None:
    probe = _row_5()

    assert probe.client.video_uploads == [b"A", b"B"]
    assert probe.client.video_attaches == [probe.videos["B"], probe.videos["A"]]


# ------------------------------------------------------------ image_ids


def test_a_video_id_in_image_ids_is_refused_and_changes_nothing() -> None:
    """Measured: `400` "That ListingImage does not exist", nothing changed."""
    import pytest

    from etsy_listings.clients.etsy.transport import EtsyApiError

    probe = _row_1()
    ids = [probe.images["1"], probe.videos["B"], probe.images["2"]]

    with pytest.raises(EtsyApiError) as caught:
        probe.client.update_listing(SHOP_ID, LISTING_ID, {"image_ids": ids})

    assert caught.value.status_code == 400
    assert caught.value.error == (
        "There was a problem with /images : That ListingImage does not exist."
    )
    assert probe.gallery() == ["1", "A", "2", "3", "4", "B", "5"]


def test_detaching_an_image_deletes_its_swatch_link_for_good() -> None:
    """Measured on duke: cut `image_ids` to one image and restore all five,
    and only the survivor's link is left. Restoring an image restores nothing
    else -- which is why the stage re-asserts swatches after every cut."""
    from etsy_listings.clients.etsy.models import VariationImageLink

    probe = Probe()
    for label in "123":
        probe.image(label)
    links = [
        VariationImageLink(property_id=513, value_id=value, image_id=probe.images[label])
        for value, label in ((1, "1"), (2, "2"), (3, "3"))
    ]
    probe.client.update_variation_images(SHOP_ID, LISTING_ID, links)

    probe.image_ids("1")
    probe.image_ids("1", "2", "3")

    remaining = probe.client.get_listing_variation_images(SHOP_ID, LISTING_ID)
    assert [link.image_id for link in remaining] == [probe.images["1"]]
    assert probe.gallery() == ["1", "2", "3"]


# --------------------------------------------------------------- limits


class Clock:
    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now


def test_a_third_active_video_is_refused_with_409() -> None:
    import pytest

    from etsy_listings.clients.etsy.listings import VideoSlotsFullError

    probe = Probe()
    probe.image("1")
    probe.video("A")
    probe.video("B")

    with pytest.raises(VideoSlotsFullError) as caught:
        probe.video("C")

    assert caught.value.status_code == 409
    assert probe.client.video_uploads == [b"A", b"B"]


def test_the_eleventh_association_in_a_day_is_refused_with_400_on_an_empty_listing() -> None:
    """Measured on duke: re-attaches count as uploads do, and the refusal
    comes with no video on the listing at all."""
    import pytest

    from etsy_listings.clients.etsy.listings import VideoBudgetExhaustedError

    probe = Probe(FakeEtsyListingClient(clock=Clock()))
    probe.image("1")
    probe.video("A")
    for _ in range(9):
        probe.delete("A")
        probe.attach("A")
    probe.delete("A")

    with pytest.raises(VideoBudgetExhaustedError) as caught:
        probe.attach("A")

    assert caught.value.status_code == 400
    assert probe.gallery() == ["1"]


def test_the_budget_is_per_listing_and_frees_up_after_24_hours() -> None:
    import pytest

    from etsy_listings.clients.etsy.listings import VideoBudgetExhaustedError

    clock = Clock()
    probe = Probe(FakeEtsyListingClient(clock=clock))
    probe.image("1")
    probe.video("A")
    for _ in range(9):
        clock.now += 60
        probe.delete("A")
        probe.attach("A")
    probe.delete("A")

    other = 4582417671
    probe.client.seed_listing(other, shop_id=SHOP_ID)
    probe.client.upload_listing_video(SHOP_ID, other, file_name="x.mp4", contents=b"x")

    clock.now += 24 * 60 * 60 - 9 * 60 - 1
    with pytest.raises(VideoBudgetExhaustedError):
        probe.attach("A")
    clock.now += 1
    probe.attach("A")

    assert probe.gallery() == ["1", "A"]


def test_an_inactive_video_stays_listed_takes_no_slot_and_does_not_show() -> None:
    """Measured after a legacy-mode upload: the others turn `inactive` but
    stay in every list, and a listing holding two inactive videos accepted
    two re-attaches, each reactivating one."""
    probe = Probe()
    probe.image("1")
    first = probe.client.seed_video(LISTING_ID, video_state="inactive")
    second = probe.client.seed_video(LISTING_ID, video_state="inactive")
    probe.videos |= {"X": first.video_id, "Y": second.video_id}

    listing = probe.client.get_listing(LISTING_ID, include_videos=True)
    assert listing is not None
    assert [(v.video_id, v.video_state) for v in listing.videos] == [
        (second.video_id, "inactive"),
        (first.video_id, "inactive"),
    ]
    assert probe.gallery() == ["1"]

    probe.attach("Y")
    probe.video("A")

    assert probe.gallery() == ["1", "Y", "A"]
    listing = probe.client.get_listing(LISTING_ID, include_videos=True)
    assert listing is not None
    assert [(v.video_id, v.video_state) for v in listing.videos] == [
        (probe.videos["A"], "active"),
        (second.video_id, "active"),
        (first.video_id, "inactive"),
    ]


def test_an_inactive_video_can_be_deleted() -> None:
    probe = Probe()
    probe.image("1")
    stale = probe.client.seed_video(LISTING_ID, video_state="inactive")

    probe.client.delete_listing_video(SHOP_ID, LISTING_ID, stale.video_id)

    listing = probe.client.get_listing(LISTING_ID, include_videos=True)
    assert listing is not None
    assert listing.videos == ()


def test_a_seeded_active_video_is_placed_like_an_attach_without_spending_budget() -> None:
    """A foreign video already on the listing -- a seller's own, uploaded in
    Shop Manager -- for the stage's sweep to find."""
    probe = Probe(FakeEtsyListingClient(clock=Clock()))
    probe.image("1")
    probe.image("2")
    foreign = probe.client.seed_video(LISTING_ID)
    probe.videos["F"] = foreign.video_id
    probe.video("A")

    assert probe.gallery() == ["1", "F", "2", "A"]
    assert probe.client.video_uploads == [b"A"]


# --------------------------------------------------- what was not measured


def test_what_decision_9_did_not_measure_is_refused_rather_than_guessed() -> None:
    """A stage that comes to depend on one of these finds out here, not
    against a real listing."""
    import pytest

    probe = Probe()
    probe.image("1")
    probe.video("A")

    with pytest.raises(ValueError, match="unmeasured: attaching .* already active"):
        probe.attach("A")
    with pytest.raises(ValueError, match="unmeasured: attaching .* never had"):
        probe.client.attach_listing_video(SHOP_ID, LISTING_ID, 1)
    probe.delete("A")
    with pytest.raises(ValueError, match="unmeasured: deleting .* not on the listing"):
        probe.delete("A")

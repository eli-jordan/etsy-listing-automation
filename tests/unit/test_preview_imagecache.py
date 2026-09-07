"""The calibrator's in-process image memo, and the downscale it hands the
editor.

Unit-level because everything here is arithmetic and bookkeeping over files:
what size an image comes back at, whether the second ask for it re-reads the
disk, and what gets thrown away when the budget is spent. Whether the
*endpoint* uses it correctly is a behaviour test.
"""

from __future__ import annotations

import os
import threading
from dataclasses import FrozenInstanceError
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from etsy_listings.ui.api.imagecache import CACHE_BUDGET_BYTES, PreviewImages, ScaledBase


@pytest.fixture
def photo(tmp_path: Path) -> Path:
    """A 400x800 photo -- portrait, so the longest edge is the height and a
    cap applied to the wrong axis would be visible."""
    path = tmp_path / "scene.png"
    rng = np.random.default_rng(0)
    Image.fromarray(rng.integers(0, 255, (800, 400, 3), dtype=np.uint8), "RGB").save(path)
    return path


@pytest.fixture
def design(tmp_path: Path) -> Path:
    path = tmp_path / "design.png"
    Image.fromarray(np.zeros((64, 64, 4), dtype=np.uint8), "RGBA").save(path)
    return path


class TestScaling:
    def test_a_photo_smaller_than_the_cap_is_left_alone(self, photo: Path) -> None:
        """No upscaling. A low-resolution mockup should look exactly as bad as
        it is, and `scale` must stay exactly 1.0 so boxes are untouched."""
        base = PreviewImages().base(photo, max_edge=2000)
        assert base.image.shape[:2] == (800, 400)
        assert base.scale == 1.0
        assert base.size == (400, 800)

    def test_a_larger_photo_is_capped_on_its_longest_edge(self, photo: Path) -> None:
        base = PreviewImages().base(photo, max_edge=200)
        # The cap is on the *longest* edge, which is the height here.
        assert base.image.shape[:2] == (200, 100)
        assert base.scale == pytest.approx(0.25)

    def test_the_true_size_survives_the_downscale(self, photo: Path) -> None:
        """The whole reason `size` exists: it is the space template.yaml's
        boxes are in, and it must not follow the image down."""
        base = PreviewImages().base(photo, max_edge=100)
        assert base.size == (400, 800)
        assert base.image.shape[1] < base.size[0]

    def test_no_cap_means_the_photo_as_it_is(self, photo: Path) -> None:
        base = PreviewImages().base(photo)
        assert base.image.shape[:2] == (800, 400)
        assert base.scale == 1.0

    def test_scale_is_measured_from_the_array_not_the_request(self, photo: Path) -> None:
        """A cap that does not divide evenly rounds to whole pixels, and a box
        scaled by the *requested* ratio would sit fractionally off the canvas
        it lands on."""
        base = PreviewImages().base(photo, max_edge=333)
        assert base.scale == base.image.shape[1] / base.size[0]


class TestMemo:
    def test_the_second_ask_does_not_decode_again(self, photo: Path) -> None:
        images = PreviewImages()
        assert images.base(photo, 200).image is images.base(photo, 200).image

    def test_two_sizes_of_one_photo_are_two_entries(self, photo: Path) -> None:
        images = PreviewImages()
        assert images.base(photo, 200).image is not images.base(photo).image

    def test_editing_the_photo_invalidates_it(self, photo: Path) -> None:
        images = PreviewImages()
        first = images.base(photo, 200)
        Image.fromarray(np.zeros((800, 400, 3), dtype=np.uint8), "RGB").save(photo)
        # Written in the same second on a coarse clock, so the mtime is nudged
        # explicitly rather than relying on the filesystem's resolution.
        stat = photo.stat()
        os.utime(photo, ns=(stat.st_atime_ns, stat.st_mtime_ns + 10**9))
        assert images.base(photo, 200).image is not first.image

    def test_a_design_is_decoded_once(self, design: Path) -> None:
        images = PreviewImages()
        assert images.design(design) is images.design(design)

    def test_derived_maps_are_memoised_and_still_written_to_disk(
        self, photo: Path, tmp_path: Path
    ) -> None:
        images = PreviewImages()
        derived = tmp_path / "_derived"
        base = images.base(photo, 200)

        first = images.height(derived, "black", base)
        assert images.height(derived, "black", base) is first
        assert images.luminance(derived, "black", base) is not first
        # Still goes through the same on-disk cache the render stage uses --
        # this only puts a memo in front of it.
        assert sorted(p.name.split("-")[1] for p in derived.glob("*.npy")) == [
            "height",
            "luminance",
        ]

    def test_a_map_of_a_different_size_of_the_same_photo_is_a_different_map(
        self, photo: Path, tmp_path: Path
    ) -> None:
        images = PreviewImages()
        derived = tmp_path / "_derived"
        small = images.height(derived, "black", images.base(photo, 200))
        full = images.height(derived, "black", images.base(photo))
        assert small.shape != full.shape

    def test_a_missing_file_is_the_caller_s_error_not_a_stale_hit(self, tmp_path: Path) -> None:
        with pytest.raises(OSError):
            PreviewImages().base(tmp_path / "gone.png", 200)


class TestBudget:
    def test_arrays_are_handed_out_read_only(self, photo: Path) -> None:
        """Every render pass is pure (A7), so nothing should want to write to
        one -- and a future accident should fail here rather than corrupt what
        the next request is served."""
        base = PreviewImages().base(photo, 200)
        with pytest.raises(ValueError):
            base.image[0, 0, 0] = 1

    def test_the_least_recently_used_entry_goes_first(self, photo: Path, tmp_path: Path) -> None:
        other = tmp_path / "second.png"
        Image.fromarray(np.zeros((800, 400, 3), dtype=np.uint8), "RGB").save(other)
        # Room for one 100x200 base (60_000 bytes) and not two.
        images = PreviewImages(budget_bytes=100_000)

        first = images.base(photo, 200)
        images.base(other, 200)
        assert images.held_bytes <= 100_000
        assert images.base(photo, 200).image is not first.image

    def test_an_entry_larger_than_the_whole_budget_is_served_but_not_kept(
        self, photo: Path
    ) -> None:
        """Caching it would evict everything else and then itself."""
        images = PreviewImages(budget_bytes=1_000)
        assert images.base(photo, 200).image.shape[:2] == (200, 100)
        assert images.held_bytes == 0

    def test_clearing_drops_everything(self, photo: Path) -> None:
        images = PreviewImages()
        images.base(photo, 200)
        assert images.held_bytes > 0
        images.clear()
        assert images.held_bytes == 0

    def test_the_default_budget_is_generous_enough_for_a_real_pair(self) -> None:
        """A 4500x5400 RGBA design is ~97MB and a full-size photo ~50MB; a
        budget that cannot hold both at once memoises nothing during the one
        loop this exists for."""
        assert CACHE_BUDGET_BYTES > 200 * 1024 * 1024


def test_scaled_base_is_frozen(photo: Path) -> None:
    """It is handed straight to the endpoint's coordinate arithmetic, so a
    scale that could be reassigned is a box that could be placed twice."""
    base = PreviewImages().base(photo, 200)
    assert isinstance(base, ScaledBase)
    with pytest.raises(FrozenInstanceError):
        base.scale = 0.5  # type: ignore[misc]


def test_two_threads_asking_at_once_get_the_same_array(photo: Path) -> None:
    """FastAPI runs the preview endpoint on a thread pool, so two previews can
    be in flight at once. Decoding twice is acceptable -- holding the lock
    across a 20-megapixel decode is not -- but handing out two arrays and
    counting both against the budget is not: the byte accounting would drift
    up until the cache evicted everything.
    """
    images = PreviewImages()
    barrier = threading.Barrier(2)
    results: list[object] = []

    def ask() -> None:
        barrier.wait()
        results.append(images.base(photo, 200).image)

    threads = [threading.Thread(target=ask) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert results[0] is results[1]
    assert images.held_bytes == 200 * 100 * 3

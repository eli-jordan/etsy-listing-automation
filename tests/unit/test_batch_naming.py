"""`naming.allocate` (A38; spec *Cleaning and editing names*): the base name
when it is free, else the smallest free ``-N`` from 2, judged casefolded
against everything a name must not collide with."""

from __future__ import annotations

from etsy_listings.batches.naming import allocate


def test_a_free_base_name_is_kept() -> None:
    assert allocate("night-hike-club", {"take-a-hike"}) == "night-hike-club"


def test_a_taken_base_name_gets_the_suffix_2() -> None:
    assert allocate("after-rain-trail", {"after-rain-trail"}) == "after-rain-trail-2"


def test_a_taken_2_is_skipped_for_the_smallest_free_suffix() -> None:
    taken = {"moss", "moss-2", "moss-3", "moss-5"}

    assert allocate("moss", taken) == "moss-4"


def test_a_design_stem_counts_as_taken_as_well_as_a_listing() -> None:
    listings = {"take-a-hike"}
    design_stems = {"cedar-trail"}

    assert allocate("cedar-trail", listings | design_stems) == "cedar-trail-2"


def test_collisions_are_casefolded_on_both_sides() -> None:
    # Windows compares directory names without case, so `Moss` on disk is
    # `moss` to the filesystem the listing directory lands on.
    assert allocate("moss", {"Moss"}) == "moss-2"
    assert allocate("Moss", {"moss", "MOSS-2"}) == "Moss-3"


def test_names_already_allocated_in_the_batch_are_taken() -> None:
    allocated: set[str] = set()
    for _ in range(3):
        allocated.add(allocate("lake-loop", allocated))

    assert allocated == {"lake-loop", "lake-loop-2", "lake-loop-3"}

"""The preamble the three Etsy stages share: which shop, which listing.

Three stages used to answer both questions for themselves -- four lockfile
lookups, two shop gates and three "no id on record" errors -- so the answers
were only ever asserted through a stage, once per stage, with a workspace and
a fake client standing in the way. They are pure, and this is where they are
tested.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from etsy_listings.engine.stage import Blocked
from etsy_listings.engine.stages.etsy_target import (
    ETSY_LISTING_ID_KEY,
    EtsyListingNotMintedError,
    check_etsy_shop,
    etsy_listing_id,
    require_etsy_listing_id,
)

from tests.support.builders import a_context, a_lock, set_etsy_shop_id

LISTING_ID = 4572550919


# ------------------------------------------------------------------ the shop


def test_a_configured_shop_is_not_a_refusal(workspace_root: Path) -> None:
    set_etsy_shop_id(workspace_root, 12345678)

    assert check_etsy_shop(a_context(workspace_root), consequence="nothing happens") is None


def test_an_unconfigured_shop_refuses_in_the_callers_terms(workspace_root: Path) -> None:
    """``Blocked``'s contract, and the reason this function takes a phrase
    rather than a whole message: the first line is the *consequence* to this
    listing, which only the calling stage knows. Writing it per stage is what
    let one of the two copies open with the cause instead."""
    blocked = check_etsy_shop(
        a_context(workspace_root), consequence="this listing's images will not be uploaded to Etsy"
    )

    assert isinstance(blocked, Blocked)
    head, *remedy = blocked.message.splitlines()
    assert head.startswith("this listing's images will not be uploaded to Etsy")
    assert "no Etsy shop is configured" in head
    assert remedy == ["Run `etsy-listings setup`, then `etsy-listings auth`, to connect one."]


# --------------------------------------------------------------- the listing


def test_no_listing_id_before_publish_has_ever_run() -> None:
    assert etsy_listing_id(a_lock()) is None


def test_the_id_publish_minted_reads_back_as_an_int() -> None:
    """JSON round-trips it, and Etsy's own ids arrive as numbers in one call
    and strings in another -- so both readers coerce, in one place."""
    assert etsy_listing_id(a_lock(remote={ETSY_LISTING_ID_KEY: str(LISTING_ID)})) == LISTING_ID
    assert etsy_listing_id(a_lock(remote={ETSY_LISTING_ID_KEY: LISTING_ID})) == LISTING_ID


def test_requiring_an_absent_id_names_the_work_that_did_not_happen() -> None:
    """A wiring defect, not a configuration problem: `publish` runs first and
    either mints one or raises, so this is a traceback on purpose."""
    with pytest.raises(EtsyListingNotMintedError) as caught:
        require_etsy_listing_id(a_lock(), to="sync media")

    assert "cannot sync media" in str(caught.value)
    assert "publish" in str(caught.value)


def test_requiring_a_present_id_answers_it() -> None:
    lock = a_lock(remote={ETSY_LISTING_ID_KEY: LISTING_ID})

    assert require_etsy_listing_id(lock, to="patch the listing") == LISTING_ID

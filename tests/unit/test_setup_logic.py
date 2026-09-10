"""The decisions `setup` makes, with no terminal and no network in sight.

Everything here is a pure function of its inputs or a small, checkable file
operation -- the same split `newcmd` uses, and for the same reason: the
sequencing of questions is the part that cannot be tested cheaply, so as
little as possible should live there.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from etsy_listings.clients.etsy.models import Shop as EtsyShop
from etsy_listings.clients.printify.models import Shop
from etsy_listings.config.defaults import Defaults
from etsy_listings.setupcmd import logic
from etsy_listings.workspace import layout

# ------------------------------------------------------------- the skeleton


def test_a_fresh_directory_is_missing_every_workspace_directory(tmp_path: Path) -> None:
    assert set(logic.missing_directories(tmp_path)) == set(logic.WORKSPACE_DIRS)


def test_directories_that_exist_are_not_reported_missing(tmp_path: Path) -> None:
    (tmp_path / layout.DESIGNS_DIR).mkdir()

    assert layout.DESIGNS_DIR not in logic.missing_directories(tmp_path)


def test_creating_the_skeleton_reports_what_it_made_and_is_idempotent(tmp_path: Path) -> None:
    created = logic.create_directories(tmp_path)
    assert set(created) == set(logic.WORKSPACE_DIRS)
    assert all((tmp_path / name).is_dir() for name in logic.WORKSPACE_DIRS)

    assert logic.create_directories(tmp_path) == ()


def test_the_skeleton_covers_the_directories_the_layout_names(tmp_path: Path) -> None:
    """A directory the tool writes to but `setup` never creates is a
    first-run failure waiting to happen."""
    for name in (
        layout.DESIGNS_DIR,
        layout.LISTINGS_DIR,
        layout.GARMENT_PROFILES_DIR,
        layout.PRICING_PLANS_DIR,
        layout.MOCKUP_TEMPLATES_DIR,
        layout.COMMON_MEDIA_DIR,
        layout.TEST_DESIGNS_DIR,
    ):
        assert name in logic.WORKSPACE_DIRS


def test_the_cache_directory_is_not_part_of_the_skeleton() -> None:
    """`.cache/` is created on demand by whatever writes into it, and is the
    one directory a user is invited to delete."""
    assert layout.CACHE_DIR not in logic.WORKSPACE_DIRS


# ------------------------------------------------------------ shop selection


def _shop(id: int, title: str = "s") -> Shop:
    return Shop(id=id, title=title, sales_channel="disconnected")


def test_a_single_shop_needs_no_question() -> None:
    selection = logic.select_shop([_shop(28819281)])

    assert selection.shop is not None
    assert selection.shop.id == 28819281
    assert selection.needs_choice is False


def test_several_shops_are_a_question_rather_than_a_guess() -> None:
    """Writing a product into the wrong shop is not a mistake worth risking
    to save one prompt."""
    selection = logic.select_shop([_shop(1, "a"), _shop(2, "b")])

    assert selection.shop is None
    assert selection.needs_choice is True


def test_no_shops_at_all_is_an_error_naming_what_to_do() -> None:
    selection = logic.select_shop([])

    assert selection.shop is None
    assert selection.needs_choice is False
    assert selection.problem is not None
    assert "printify.com" in selection.problem


# ---------------------------------------------------------------- shop.yaml


ANSWERS = logic.SetupAnswers(
    printify_shop_id=28819281,
    printify_shop_name="My new store",
    preferred_print_provider="Monster Digital",
    currency="NOK",
    who_made="someone_else",
    when_made="made_to_order",
    is_supply=False,
    renewal="manual",
)


def test_the_document_it_writes_loads_back_as_defaults(tmp_path: Path) -> None:
    """The only assertion that matters: what `setup` writes, the tool reads."""
    path = tmp_path / layout.SHOP_FILE
    path.write_text(logic.render_shop_yaml(logic.shop_yaml_document(ANSWERS, None)), "utf-8")

    defaults = Defaults.load(path)
    assert defaults.printify.require_shop_id() == 28819281
    assert defaults.printify.shop_name == "My new store"
    assert defaults.printify.preferred_print_provider == "Monster Digital"
    assert defaults.etsy.currency == "NOK"
    assert defaults.etsy.listing_defaults.who_made == "someone_else"


def test_shipping_profile_return_policy_and_production_partner_round_trip(tmp_path: Path) -> None:
    answers = logic.SetupAnswers(
        **{
            **vars(ANSWERS),
            "etsy_shipping_profile": "NOK standard tee",
            "etsy_return_policy": {
                "accepts_returns": True,
                "accepts_exchanges": True,
                "within_days": 30,
            },
            "etsy_production_partner": "The Print Provider",
        }
    )
    path = tmp_path / layout.SHOP_FILE
    path.write_text(logic.render_shop_yaml(logic.shop_yaml_document(answers, None)), "utf-8")

    listing_defaults = Defaults.load(path).etsy.listing_defaults
    assert listing_defaults.shipping_profile == "NOK standard tee"
    assert listing_defaults.production_partner == "The Print Provider"
    assert listing_defaults.return_policy is not None
    assert listing_defaults.return_policy.within_days == 30


def test_omitted_shipping_profile_and_partner_are_left_unset(tmp_path: Path) -> None:
    """Blank means "not known", never "delete it" -- same rule as the Etsy
    shop id (PRD 51's reasoning, applied to the new name-based fields)."""
    path = tmp_path / layout.SHOP_FILE
    path.write_text(logic.render_shop_yaml(logic.shop_yaml_document(ANSWERS, None)), "utf-8")

    listing_defaults = Defaults.load(path).etsy.listing_defaults
    assert listing_defaults.shipping_profile is None
    assert listing_defaults.production_partner is None
    assert listing_defaults.return_policy is None


def test_an_unknown_etsy_shop_id_is_omitted_rather_than_faked() -> None:
    """A placeholder id is worse than an absent one: it looks real enough to
    be published against in Phase 3."""
    document = logic.shop_yaml_document(ANSWERS, None)

    assert "shop_id" not in document["etsy"]
    assert "shop_name" not in document["etsy"]


def test_a_discovered_etsy_shop_is_written_as_name_and_id() -> None:
    answers = logic.SetupAnswers(
        **{**vars(ANSWERS), "etsy_shop_id": 12345678, "etsy_shop_name": "TakeAHikeTees"}
    )

    etsy = logic.shop_yaml_document(answers, None)["etsy"]

    assert etsy["shop_id"] == 12345678
    assert etsy["shop_name"] == "TakeAHikeTees"


def test_an_absent_print_provider_preference_is_omitted() -> None:
    answers = logic.SetupAnswers(**{**vars(ANSWERS), "preferred_print_provider": None})

    assert "preferred_print_provider" not in logic.shop_yaml_document(answers, None)["printify"]


def test_merging_keeps_keys_setup_does_not_ask_about() -> None:
    """Anything a later phase or a human added is theirs, and a wizard that
    drops it is a wizard nobody re-runs."""
    existing = {"etsy": {"a_later_key": 1}, "something_later": {"a": 1}}

    document = logic.shop_yaml_document(ANSWERS, existing)

    assert document["etsy"]["a_later_key"] == 1
    assert document["something_later"] == {"a": 1}


def test_an_answer_the_user_just_gave_wins_over_the_file() -> None:
    """The complement of the rule above, and the half that is easy to get
    backwards. `setup` protects what it never asked about; what it *did* ask
    about, the answer wins. Asking a question and then discarding the answer
    is worse than either -- the caller seeds the prompt with the current value,
    so pressing enter already means "leave it"."""
    existing = {"etsy": {"shop_id": 999, "currency": "USD"}}
    answers = logic.SetupAnswers(**{**vars(ANSWERS), "etsy_shop_id": 12345678})

    document = logic.shop_yaml_document(answers, existing)

    assert document["etsy"]["shop_id"] == 12345678
    assert document["etsy"]["currency"] == "NOK"


def test_ids_on_disk_survive_a_discovery_that_found_nothing() -> None:
    """``None`` means "not found", not "delete it". An Etsy lookup that failed
    -- no credentials, a network problem -- must not clear what a previous run
    resolved."""
    existing = {"etsy": {"shop_id": 999, "shop_name": "Old"}}

    etsy = logic.shop_yaml_document(ANSWERS, existing)["etsy"]

    assert (etsy["shop_id"], etsy["shop_name"]) == (999, "Old")


def test_listing_defaults_names_on_disk_survive_an_unanswered_run() -> None:
    """The shipping profile, return policy and production partner `setup`
    never asked about this run must not be cleared -- the same rule as the
    shop id, one level deeper."""
    existing = {
        "etsy": {
            "shop_id": 999,
            "listing_defaults": {
                "shipping_profile": "NOK standard tee",
                "production_partner": "The Print Provider",
                "return_policy": {"accepts_returns": True, "accepts_exchanges": True},
            },
        }
    }

    listing_defaults = logic.shop_yaml_document(ANSWERS, existing)["etsy"]["listing_defaults"]

    assert listing_defaults["shipping_profile"] == "NOK standard tee"
    assert listing_defaults["production_partner"] == "The Print Provider"
    assert listing_defaults["return_policy"] == {"accepts_returns": True, "accepts_exchanges": True}


def test_the_rendered_file_carries_a_header_saying_where_it_came_from() -> None:
    rendered = logic.render_shop_yaml(logic.shop_yaml_document(ANSWERS, None))

    assert rendered.startswith("#")
    assert "setup" in rendered.splitlines()[0]


def test_the_rendered_file_points_at_env_for_the_credentials() -> None:
    """`shop.yaml` is the file people open looking for their tokens, and it is
    the one file in the workspace that must never hold them."""
    rendered = logic.render_shop_yaml(logic.shop_yaml_document(ANSWERS, None))

    assert ".env" in rendered
    assert "auth" in rendered


def test_every_field_written_carries_a_comment() -> None:
    """The point of the comments is that a reader never meets a bare number.
    A field added later without one would go unnoticed, so the check walks
    every level the document actually has -- including `listing_defaults`,
    two deep."""
    answers = logic.SetupAnswers(
        **{
            **vars(ANSWERS),
            "etsy_shop_name": "TakeAHikeTees",
            "etsy_shop_id": 12345678,
            "etsy_shipping_profile": "NOK standard tee",
            "etsy_production_partner": "The Print Provider",
        }
    )
    document = logic.shop_yaml_document(answers, None)

    rendered = logic.render_shop_yaml(document)
    lines = rendered.splitlines()

    def check(mapping: dict, path: str) -> None:
        for field, value in mapping.items():
            index = next(i for i, line in enumerate(lines) if line.strip().startswith(f"{field}:"))
            assert lines[index - 1].strip().startswith("#"), f"{path}.{field} has no comment"
            if isinstance(value, dict):
                check(value, f"{path}.{field}")

    for section, fields in document.items():
        check(fields, section)


def test_the_rendered_file_is_valid_yaml_with_printify_first() -> None:
    rendered = logic.render_shop_yaml(logic.shop_yaml_document(ANSWERS, None))
    parsed = yaml.safe_load(rendered)

    assert list(parsed) == ["printify", "etsy"]


# ------------------------------------------------------- matching an Etsy shop


def _etsy_shop(name: str, shop_id: int) -> EtsyShop:
    return EtsyShop(shop_id=shop_id, shop_name=name)


def test_one_exact_match_is_the_answer() -> None:
    found = logic.exact_shop_match(
        [_etsy_shop("TakeAHike", 1), _etsy_shop("TakeAHikeVintage", 2)], "takeahike"
    )

    assert found is not None
    assert found.shop_id == 1


def test_a_near_match_is_not_taken_as_the_answer() -> None:
    """Etsy's shop search is built for buyers browsing, not for resolving an
    identifier. Taking the first row would point a workspace at a stranger's
    shop."""
    assert logic.exact_shop_match([_etsy_shop("TakeAHikeVintage", 2)], "TakeAHike") is None


def test_no_candidates_is_no_answer() -> None:
    assert logic.exact_shop_match([], "TakeAHike") is None

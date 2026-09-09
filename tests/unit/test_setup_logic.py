"""The decisions `setup` makes, with no terminal and no network in sight.

Everything here is a pure function of its inputs or a small, checkable file
operation -- the same split `newcmd` uses, and for the same reason: the
sequencing of questions is the part that cannot be tested cheaply, so as
little as possible should live there.
"""

from __future__ import annotations

from pathlib import Path

import yaml

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
        layout.PROFILES_DIR,
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
    currency="NOK",
    who_made="i_did",
    when_made="made_to_order",
    is_supply=False,
    renewal="manual",
    preferred_print_provider="Monster Digital",
    etsy_shop_id=None,
)


def test_the_document_it_writes_loads_back_as_defaults(tmp_path: Path) -> None:
    """The only assertion that matters: what `setup` writes, the tool reads."""
    path = tmp_path / layout.SHOP_FILE
    path.write_text(logic.render_shop_yaml(logic.shop_yaml_document(ANSWERS, None)), "utf-8")

    defaults = Defaults.load(path)
    assert defaults.printify.require_shop_id() == 28819281
    assert defaults.currency == "NOK"
    assert defaults.preferred_print_provider == "Monster Digital"
    assert defaults.etsy.who_made == "i_did"


def test_an_unknown_etsy_shop_id_is_omitted_rather_than_faked() -> None:
    """A placeholder id is worse than an absent one: it looks real enough to
    be published against in Phase 3."""
    document = logic.shop_yaml_document(ANSWERS, None)

    assert "shop_id" not in document["etsy"]


def test_a_known_etsy_shop_id_is_written() -> None:
    answers = logic.SetupAnswers(**{**vars(ANSWERS), "etsy_shop_id": 12345678})

    assert logic.shop_yaml_document(answers, None)["etsy"]["shop_id"] == 12345678


def test_an_absent_print_provider_preference_is_omitted() -> None:
    answers = logic.SetupAnswers(**{**vars(ANSWERS), "preferred_print_provider": None})

    assert "preferred_print_provider" not in logic.shop_yaml_document(answers, None)


def test_merging_keeps_keys_setup_does_not_ask_about(tmp_path: Path) -> None:
    """Re-running `setup` on a workspace that reached Phase 3 must not drop
    the ids that phase filled in."""
    existing = {
        "etsy": {
            "shop_id": 999,
            "who_made": "i_did",
            "when_made": "made_to_order",
            "is_supply": False,
            "shop_section_id": 44,
            "return_policy_id": 55,
        },
        "currency": "NOK",
    }

    document = logic.shop_yaml_document(ANSWERS, existing)

    assert document["etsy"]["shop_section_id"] == 44
    assert document["etsy"]["return_policy_id"] == 55


def test_merging_keeps_top_level_keys_setup_does_not_ask_about() -> None:
    """Not just the Etsy ids: anything a later phase or a human added at the
    top level is theirs, and a wizard that drops it is a wizard nobody re-runs."""
    existing = {"currency": "NOK", "something_later": {"a": 1}}

    document = logic.shop_yaml_document(ANSWERS, existing)

    assert document["something_later"] == {"a": 1}


def test_an_answer_the_user_just_gave_wins_over_the_file() -> None:
    """The complement of the rule above, and the half that is easy to get
    backwards. `setup` protects what it never asked about; what it *did* ask
    about, the answer wins. Asking a question and then discarding the answer
    is worse than either -- the caller seeds the prompt with the current value,
    so pressing enter already means "leave it"."""
    existing = {"etsy": {"shop_id": 999}, "currency": "USD"}
    answers = logic.SetupAnswers(**{**vars(ANSWERS), "etsy_shop_id": 12345678})

    document = logic.shop_yaml_document(answers, existing)

    assert document["etsy"]["shop_id"] == 12345678
    assert document["currency"] == "NOK"


def test_an_etsy_shop_id_on_disk_survives_an_answer_of_none() -> None:
    """`None` here means "not asked / not known", not "delete it" -- the
    prompt cannot return blank for a field it seeded with a value."""
    existing = {"etsy": {"shop_id": 999}}

    document = logic.shop_yaml_document(ANSWERS, existing)

    assert document["etsy"]["shop_id"] == 999


def test_the_rendered_file_carries_a_header_saying_where_it_came_from() -> None:
    rendered = logic.render_shop_yaml(logic.shop_yaml_document(ANSWERS, None))

    assert rendered.startswith("#")
    assert "setup" in rendered.splitlines()[0]


def test_the_rendered_file_is_valid_yaml_with_printify_first() -> None:
    rendered = logic.render_shop_yaml(logic.shop_yaml_document(ANSWERS, None))
    parsed = yaml.safe_load(rendered)

    assert list(parsed) == ["printify", "etsy", "currency", "preferred_print_provider"]

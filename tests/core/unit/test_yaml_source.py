"""`edit_yaml`: a YAML document with new values, every other byte as it was.

ADR-0055. The expected texts are golden: written out by hand, never derived
by dumping, so a test fails when an untouched comment, quote, indent or line
ending moves."""

from __future__ import annotations

import pytest
import yaml

from etsy_listings.core.workspace.yaml_source import UneditableYaml, edit_yaml, edit_yaml_bytes

SOURCE = """\
# Shop-wide settings -- my notes stay.
printify:
  shop_name: 'My Shop'   # single-quoted on purpose
  shop_id: 123
etsy:
  currency: "GBP"
  listing_defaults:
    who_made: someone_else  # the printer makes it
    tags: [cotton, gift,  "tee"]
    renewal: manual

    # blank line and comment above stay
    is_supply: false
description: |
  Line one.
  Línea dos — ünïcödé.

colors:
- black   # dark first
- white
"""


def test_a_semantic_no_op_returns_the_source_unchanged() -> None:
    reordered = {"etsy": yaml.safe_load(SOURCE)["etsy"], **yaml.safe_load(SOURCE)}

    assert edit_yaml(SOURCE, reordered) is SOURCE


def test_a_scalar_edit_changes_only_that_value() -> None:
    document = yaml.safe_load(SOURCE)
    document["printify"]["shop_id"] = 456

    assert edit_yaml(SOURCE, document) == SOURCE.replace("shop_id: 123", "shop_id: 456")


def test_a_quoted_string_keeps_its_quote_style() -> None:
    document = yaml.safe_load(SOURCE)
    document["printify"]["shop_name"] = "Other Shop"
    document["etsy"]["currency"] = "EUR"

    assert edit_yaml(SOURCE, document) == SOURCE.replace("'My Shop'", "'Other Shop'").replace(
        '"GBP"', '"EUR"'
    )


def test_a_string_that_would_read_back_as_another_type_is_quoted() -> None:
    document = yaml.safe_load(SOURCE)
    document["etsy"]["listing_defaults"]["renewal"] = "yes"

    edited = edit_yaml(SOURCE, document)

    assert edited == SOURCE.replace("renewal: manual", "renewal: 'yes'")
    assert yaml.safe_load(edited) == document


def test_a_nested_edit_inside_a_flow_collection_keeps_its_spacing() -> None:
    document = yaml.safe_load(SOURCE)
    document["etsy"]["listing_defaults"]["tags"][1] = "present, wrapped"

    assert edit_yaml(SOURCE, document) == SOURCE.replace("gift,", "'present, wrapped',")


def test_growing_a_flow_collection_rewrites_only_that_collection() -> None:
    document = yaml.safe_load(SOURCE)
    document["etsy"]["listing_defaults"]["tags"].append("summer")

    assert edit_yaml(SOURCE, document) == SOURCE.replace(
        '[cotton, gift,  "tee"]', "[cotton, gift, tee, summer]"
    )


def test_a_block_scalar_stays_a_block_scalar() -> None:
    document = yaml.safe_load(SOURCE)
    document["description"] = "Line one.\nLine two, edited — ünïcödé.\n"

    assert edit_yaml(SOURCE, document) == SOURCE.replace(
        "  Línea dos — ünïcödé.\n", "  Line two, edited — ünïcödé.\n"
    )


def test_a_new_key_lands_after_its_predecessor_at_the_mapping_indent() -> None:
    document = yaml.safe_load(SOURCE)
    defaults = document["etsy"]["listing_defaults"]
    document["etsy"]["listing_defaults"] = {
        "who_made": defaults["who_made"],
        "when_made": "made_to_order",
        **defaults,
    }

    assert edit_yaml(SOURCE, document) == SOURCE.replace(
        "    who_made: someone_else  # the printer makes it\n",
        "    who_made: someone_else  # the printer makes it\n    when_made: made_to_order\n",
    )


def test_a_new_nested_mapping_is_written_in_block_style() -> None:
    document = yaml.safe_load(SOURCE)
    document["printify"]["preferred"] = {"name": "Monster Digital", "ids": [1, 2]}

    assert edit_yaml(SOURCE, document) == SOURCE.replace(
        "  shop_id: 123\n",
        "  shop_id: 123\n  preferred:\n    name: Monster Digital\n    ids:\n    - 1\n    - 2\n",
    )


def test_a_removed_key_takes_its_line_and_comment_with_it() -> None:
    document = yaml.safe_load(SOURCE)
    del document["etsy"]["listing_defaults"]["who_made"]

    assert edit_yaml(SOURCE, document) == SOURCE.replace(
        "    who_made: someone_else  # the printer makes it\n", ""
    )


def test_block_sequence_items_are_appended_and_removed_in_place() -> None:
    document = yaml.safe_load(SOURCE)
    document["colors"] = ["black", "navy"]

    assert edit_yaml(SOURCE, document) == SOURCE.replace("- white\n", "- navy\n")

    document["colors"] = ["black", "white", "navy"]
    assert edit_yaml(SOURCE, document) == SOURCE + "- navy\n"

    document["colors"] = ["white"]
    assert edit_yaml(SOURCE, document) == SOURCE.replace("- black   # dark first\n", "")


def test_a_scalar_becoming_a_mapping_moves_to_block_style() -> None:
    source = "design: front.png  # the old form\ntitle: Tee\n"

    edited = edit_yaml(source, {"design": {"default": "front.png"}, "title": "Tee"})

    assert edited == "design:\n  default: front.png  # the old form\ntitle: Tee\n"


def test_crlf_line_endings_are_kept_and_used_for_new_lines() -> None:
    source = SOURCE.replace("\n", "\r\n")
    document = yaml.safe_load(SOURCE)
    document["printify"]["preferred"] = {"name": "Monster Digital"}
    document["printify"]["shop_id"] = 456

    assert edit_yaml(source, document) == source.replace(
        "  shop_id: 123\r\n", "  shop_id: 456\r\n  preferred:\r\n    name: Monster Digital\r\n"
    )


def test_an_lf_file_without_a_final_newline_gains_none_on_a_scalar_edit() -> None:
    assert edit_yaml("a: 1\nb: 2", {"a": 1, "b": 3}) == "a: 1\nb: 3"


def test_indented_sequences_keep_their_offset_for_new_items() -> None:
    source = "sizes:\n  - S   # small\n  - M\n"

    assert (
        edit_yaml(source, {"sizes": ["S", "M", "L"]}) == "sizes:\n  - S   # small\n  - M\n  - L\n"
    )


def test_a_three_way_edit_applies_only_what_changed_between_the_models() -> None:
    """A model dump fills defaults the seller never wrote. Only the values
    that differ between the before and after dumps reach the file."""
    source = "price: 25  # hand-written\n"
    before = {"price": "25.00", "renewal": "manual"}
    after = {"price": "25.00", "renewal": "auto"}

    assert edit_yaml(source, after, before=before) == source + "renewal: auto\n"
    assert edit_yaml(source, before, before=before) is source


def test_an_empty_document_gains_the_new_content_after_its_comments() -> None:
    assert edit_yaml("# only notes\n", {"a": 1}) == "# only notes\na: 1\n"


def test_bytes_keep_a_byte_order_mark_and_a_no_op_returns_the_same_bytes() -> None:
    source = "﻿a: 1  # note\r\n".encode()

    assert edit_yaml_bytes(source, {"a": 1}) is source
    assert edit_yaml_bytes(source, {"a": 2}) == "﻿a: 2  # note\r\n".encode()


def test_an_edit_through_an_alias_is_refused_rather_than_written_wrong() -> None:
    source = "base: &b {x: 1}\nother: *b\n"

    with pytest.raises(UneditableYaml):
        edit_yaml(source, {"base": {"x": 2}, "other": {"x": 1}})


MEDIA = """\
media:
- file: ./front.png   # thumbnail
  alt: Front
- file: ./back.png
  alt: Back
notes:
"""


def test_an_edit_inside_a_mapping_in_a_sequence_touches_only_that_value() -> None:
    document = yaml.safe_load(MEDIA)
    document["media"][1]["alt"] = "Back view"

    assert edit_yaml(MEDIA, document) == MEDIA.replace("alt: Back\n", "alt: Back view\n")


def test_removing_the_first_key_of_an_item_rewrites_only_that_item() -> None:
    document = yaml.safe_load(MEDIA)
    del document["media"][0]["file"]

    assert edit_yaml(MEDIA, document) == MEDIA.replace(
        "- file: ./front.png   # thumbnail\n  alt: Front\n", "- alt: Front\n"
    )


def test_a_new_item_mapping_is_appended_in_block_style() -> None:
    document = yaml.safe_load(MEDIA)
    document["media"].append({"file": "./side.png", "alt": None})

    assert edit_yaml(MEDIA, document) == MEDIA.replace(
        "  alt: Back\n", "  alt: Back\n- file: ./side.png\n  alt: null\n"
    )


def test_an_empty_value_gains_one_in_place() -> None:
    document = yaml.safe_load(MEDIA)
    document["notes"] = "two words"

    assert edit_yaml(MEDIA, document) == MEDIA.replace("notes:\n", "notes: two words\n")


def test_emptying_a_mapping_writes_an_empty_flow_mapping() -> None:
    assert edit_yaml("a:\n  b: 1  # gone\nc: 2\n", {"a": {}, "c": 2}) == "a: {}\nc: 2\n"


def test_replacing_every_key_of_a_nested_mapping_keeps_the_new_ones_nested() -> None:
    source = "renderer:\n  type: marigold\n  config:\n    inference:\n      steps: 10\n"

    edited = edit_yaml(
        source, {"renderer": {"type": "photo-warp", "config": {"warp": {"opacity": 0.6}}}}
    )

    assert edited == "renderer:\n  type: photo-warp\n  config:\n    warp:\n      opacity: 0.6\n"


def test_replacing_every_item_of_a_sequence_keeps_its_indent() -> None:
    assert edit_yaml("a:\n  - x\n  - y\n", {"a": ["z"]}) == "a:\n  - z\n"
    assert edit_yaml("a:\n  - x\n  - y\n", {"a": ["p", "q", "r"]}) == "a:\n  - p\n  - q\n  - r\n"


def test_keys_read_as_the_workspace_reader_reads_them() -> None:
    """PyYAML reads a plain `y` key as the string ``"y"``; ruamel's YAML 1.1
    rules would make it ``True``."""
    source = "points:\n- {x: 0, y: 0}\n- x: 1\n  y: 1\n"

    edited = edit_yaml(source, {"points": [{"x": 0, "y": 5}, {"x": 1, "y": 2}]})

    assert edited == "points:\n- {x: 0, y: 5}\n- x: 1\n  y: 2\n"

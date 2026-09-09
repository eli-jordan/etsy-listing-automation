"""Builders for what a behaviour test needs before it can assert anything.

Two kinds of thing live here.

*Objects*: :func:`a_lock` and :func:`a_context` are the two the engine's entry
points demand, and every behaviour file was constructing them from scratch
with slightly different defaults.

*Workspace edits*: the fixture workspace is a fixed set of YAML files copied
per test (see the ``workspace_root`` fixture), so a test that needs a listing
with different prices has to edit one. Doing that inline means four lines of
``yaml.safe_load`` / ``update`` / ``safe_dump`` around the single key the test
actually cares about, and it means a change to ``listing.yaml``'s shape has to
be made in every file that does it. These wrap the round-trip so the call site
shows only what varies.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml
from PIL import Image

from etsy_listings import __about__
from etsy_listings.clients.printify.fakes import FakeCatalogClient
from etsy_listings.clients.printify.protocol import CatalogClient, PrintifyClient
from etsy_listings.engine.context import Event, RunContext
from etsy_listings.engine.lock import Lockfile
from etsy_listings.workspace.workspace import Workspace

FIXTURE_LISTING = "take-a-hike"
"""The listing in ``tests/fixtures/workspace``. Named rather than repeated,
because "take-a-hike" appearing in a test is usually incidental -- it means
"the listing that exists", not that anything about hiking matters."""

APPLIED_AT = "2026-09-08T00:00:00Z"
"""A fixed stamp, not ``datetime.now()``. ``applied_at`` never enters a hash
(A2), so a clock here buys nothing and costs determinism -- two lockfiles built
in the same test would otherwise differ in a field that is supposed not to
matter, which is exactly the thing the hashing rules are hard to reason about."""


def a_lock(**overrides: Any) -> Lockfile:
    """A lockfile carrying whatever axes the test is about, and nothing else.

    ``tool_version`` and ``applied_at`` are defaulted because every caller
    needs them and almost none cares: they are excluded from the hash by
    design. Both stay overridable -- a test about *stamping* has to be able to
    set them.
    """
    return Lockfile(**{"tool_version": __about__.VERSION, "applied_at": APPLIED_AT, **overrides})


def a_context(
    root: Path,
    *,
    catalog: CatalogClient | None = None,
    printify: PrintifyClient | None = None,
    on_event: Callable[[Event], None] | None = None,
) -> RunContext:
    """A run context over the workspace at ``root``.

    The catalog defaults to an empty fake rather than to ``None``: a stage may
    hold a catalog client it never calls (``plan`` builds one to avoid
    demanding a token), so "no catalog data" and "no catalog" are different
    states and the honest default is the former.
    """
    sink = {"on_event": on_event} if on_event is not None else {}
    return RunContext(
        workspace=Workspace.discover(root_override=root),
        catalog=catalog if catalog is not None else FakeCatalogClient([], {}, {}),
        printify=printify,
        **sink,
    )


# ----------------------------------------------------------- workspace edits


def _read_yaml(path: Path) -> dict[str, Any]:
    document: dict[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return document


def _write_yaml(path: Path, document: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(document), encoding="utf-8")


def listing_file(root: Path, listing: str = FIXTURE_LISTING) -> Path:
    return root / "listings" / listing / "listing.yaml"


def edit_listing(root: Path, listing: str = FIXTURE_LISTING, **updates: Any) -> None:
    """Replace top-level keys of a listing -- ``prices``, ``colors``, ``media``."""
    path = listing_file(root, listing)
    document = _read_yaml(path)
    document.update(updates)
    _write_yaml(path, document)


def set_copy(
    root: Path,
    *,
    title: str,
    description: str,
    listing: str = FIXTURE_LISTING,
) -> None:
    """Write real Etsy copy over the fixture's ``<generate>`` sentinels.

    Its own function rather than an ``edit_listing(etsy={...})`` call, because
    replacing the whole ``etsy:`` block would drop ``tags``, ``materials`` and
    ``renewal`` -- and a listing missing those fails validation for a reason
    that has nothing to do with the test that dropped them.
    """
    path = listing_file(root, listing)
    document = _read_yaml(path)
    document["etsy"] = {**document["etsy"], "title": title, "description": description}
    _write_yaml(path, document)


def copy_listing(
    root: Path,
    name: str,
    *,
    source: str = FIXTURE_LISTING,
    **overrides: Any,
) -> Path:
    """A second listing, filed under ``name``: the fixture's document with
    top-level keys replaced. Returns the directory it was written to."""
    document = _read_yaml(listing_file(root, source))
    document.update(overrides)
    target = root / "listings" / name
    target.mkdir(parents=True, exist_ok=True)
    _write_yaml(target / "listing.yaml", document)
    return target


def set_shop_id(root: Path, shop_id: int) -> Path:
    """Opt the workspace into Phase 2. Returns ``root``, so a test that needs
    a configured workspace can say so in one line."""
    path = root / "shop.yaml"
    document = _read_yaml(path)
    # Merged, not replaced: the fixture's `preferred_print_provider` lives in
    # this block too (PRD 51), and a helper that quietly dropped it would
    # change what the product stage offers.
    document["printify"] = {**(document.get("printify") or {}), "shop_id": shop_id}
    _write_yaml(path, document)
    return root


def write_design(root: Path, size: tuple[int, int], *, name: str = FIXTURE_LISTING) -> Path:
    """Replace a design with a solid image of a given pixel size.

    The size is the point: the product stage refuses a design smaller than the
    profile's print area, so "at print resolution" and "too small" are both
    just a number here.
    """
    path = root / "designs" / f"{name}.png"
    Image.new("RGBA", size, (10, 20, 30, 255)).save(path)
    return path

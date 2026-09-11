"""Every decision ``setup`` makes, as a function of its inputs.

Pure where it can be, and a small checkable file operation where it cannot --
the same split ``newcmd`` uses (``logic`` decides, ``interactive`` asks), and
for the same reason: sequencing questions is the one part no test can drive
cheaply, so as little as possible belongs there.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from etsy_listings.clients.etsy.models import Shop as EtsyShop
from etsy_listings.clients.printify.models import Shop
from etsy_listings.workspace import layout

WORKSPACE_DIRS: tuple[str, ...] = (
    layout.DESIGNS_DIR,
    layout.LISTINGS_DIR,
    layout.GARMENT_PROFILES_DIR,
    layout.PRICING_PLANS_DIR,
    layout.MOCKUP_TEMPLATES_DIR,
    layout.COMMON_MEDIA_DIR,
    layout.TEST_DESIGNS_DIR,
    layout.PROMPTS_DIR,
)
"""The directories a workspace is expected to have.

``.cache/`` is deliberately absent: it is created on demand by whatever writes
into it, and it is the one directory users are invited to delete. Creating it
here would suggest it is structural, which is exactly the misunderstanding
``plan``'s "is the output still there?" check exists to survive.
"""


def missing_directories(root: Path) -> tuple[str, ...]:
    return tuple(name for name in WORKSPACE_DIRS if not (root / name).is_dir())


def create_directories(root: Path) -> tuple[str, ...]:
    """Create what is missing; return what was actually created.

    Returning the difference rather than the whole list is what lets a re-run
    say "nothing to do" honestly instead of reporting work it did not do.
    """
    created = missing_directories(root)
    for name in created:
        (root / name).mkdir(parents=True, exist_ok=True)
    return created


@dataclass(frozen=True)
class ShopSelection:
    """The outcome of asking Printify which shops a token can reach.

    Three outcomes, not two: exactly one shop answers the question outright,
    several make it a question for the user, and none is a problem no prompt
    can fix.
    """

    shop: Shop | None = None
    needs_choice: bool = False
    problem: str | None = None


def select_shop(shops: Sequence[Shop]) -> ShopSelection:
    if not shops:
        return ShopSelection(
            problem=(
                "this Printify account has no shops, so there is nowhere to create "
                "products. Create one at printify.com (My stores -> Add new store); "
                "an 'API' store is enough for everything up to publishing."
            )
        )
    if len(shops) == 1:
        return ShopSelection(shop=shops[0])
    return ShopSelection(needs_choice=True)


def exact_shop_match(candidates: Sequence[EtsyShop], name: str) -> EtsyShop | None:
    """The one shop whose name *is* ``name``, or ``None``.

    Etsy's shop search matches loosely -- it is built for buyers browsing, not
    for resolving an identifier -- so "TakeAHike" can come back alongside
    "TakeAHikeVintage" and a dozen others. Taking the first row would give a
    workspace that publishes to a stranger's shop, so anything less certain
    than a single exact match (case aside) is treated as no answer at all and
    put in front of the user.
    """
    matches = [shop for shop in candidates if shop.shop_name.casefold() == name.casefold()]
    return matches[0] if len(matches) == 1 else None


@dataclass(frozen=True)
class SetupAnswers:
    """Everything ``setup`` collects, in one value the renderer can be tested
    against without a terminal."""

    printify_shop_id: int
    printify_shop_name: str
    preferred_print_provider: str | None
    currency: str
    who_made: str
    when_made: str
    is_supply: bool
    renewal: str
    etsy_shop_name: str | None = None
    etsy_shop_id: int | None = None
    etsy_shipping_profile: str | None = None
    """By name (PRD 54). Free text: resolving it against the shop's live list
    needs `shops_r` and a bearer, which `setup` may not have -- that
    resolution happens once per run in `EtsyShopCatalog`, at plan time."""
    etsy_return_policy: dict[str, Any] | None = None
    """The three terms (`accepts_returns`, `accepts_exchanges`,
    `within_days`), since Etsy gives the resource no title (PRD 59). Built
    from a live pick when the discovery step can reach the Etsy API."""
    etsy_production_partner: str | None = None
    """By name; omitted when the shop has exactly one (decision 3's
    resolution ladder), same free-text reasoning as ``etsy_shipping_profile``."""


ASKED_PRINTIFY_KEYS = ("shop_name", "shop_id", "preferred_print_provider")
ASKED_ETSY_KEYS = ("shop_name", "shop_id", "currency")
ASKED_LISTING_DEFAULT_KEYS = (
    "who_made",
    "when_made",
    "is_supply",
    "renewal",
    "shipping_profile",
    "return_policy",
    "production_partner",
)
ASKED_TOP_LEVEL_KEYS = ("printify", "etsy")
"""What ``setup`` puts a question in front of the user for, or resolves on
their behalf.

The split matters, and it is the half that is easy to get backwards. Anything
*not* named here -- any key a later version adds -- is carried through
untouched, because dropping a value nobody was asked about is how a re-runnable
command becomes a destructive one.
"""


def shop_yaml_document(answers: SetupAnswers, existing: dict[str, Any] | None) -> dict[str, Any]:
    """The ``shop.yaml`` mapping to write, merged over whatever is there.

    Two rules, and they are complements rather than a compromise:

    - **What ``setup`` never asked about is kept**, verbatim. See
      :data:`ASKED_ETSY_KEYS` and :data:`ASKED_LISTING_DEFAULT_KEYS`.
    - **What it did ask about, the answer wins.** Asking a question and then
      discarding the answer is worse than either overwriting or not asking:
      it silently tells the user their input does not matter. The caller seeds
      each prompt with the value already on disk, so pressing enter through a
      re-run keeps everything -- which is what makes this safe.

    ``None`` for an optional answer means "not known", never "delete it": a
    prompt seeded with a value cannot come back blank, and a discovery that
    found nothing must not erase what a previous run found. That rule now
    applies one level deeper too -- ``listing_defaults``' own optional names.
    """
    prior: dict[str, Any] = dict(existing or {})
    prior_etsy: dict[str, Any] = dict(prior.get("etsy") or {})
    prior_printify: dict[str, Any] = dict(prior.get("printify") or {})
    prior_listing_defaults: dict[str, Any] = dict(prior_etsy.get("listing_defaults") or {})

    printify: dict[str, Any] = {
        k: v for k, v in prior_printify.items() if k not in ASKED_PRINTIFY_KEYS
    }
    printify.update({"shop_name": answers.printify_shop_name, "shop_id": answers.printify_shop_id})
    if answers.preferred_print_provider:
        printify["preferred_print_provider"] = answers.preferred_print_provider

    etsy: dict[str, Any] = {
        k: v for k, v in prior_etsy.items() if k not in (*ASKED_ETSY_KEYS, "listing_defaults")
    }
    for key, answer in (("shop_name", answers.etsy_shop_name), ("shop_id", answers.etsy_shop_id)):
        # Omitted rather than defaulted when unknown: a placeholder id looks
        # real enough to be published against, which is how `12345678` ended
        # up in a workspace that had no Etsy shop at all.
        kept = answer if answer is not None else prior_etsy.get(key)
        if kept is not None:
            etsy[key] = kept
    etsy["currency"] = answers.currency

    listing_defaults: dict[str, Any] = {
        k: v for k, v in prior_listing_defaults.items() if k not in ASKED_LISTING_DEFAULT_KEYS
    }
    listing_defaults.update(
        {
            "who_made": answers.who_made,
            "when_made": answers.when_made,
            "is_supply": answers.is_supply,
            "renewal": answers.renewal,
        }
    )
    for key, answer in (
        ("shipping_profile", answers.etsy_shipping_profile),
        ("production_partner", answers.etsy_production_partner),
    ):
        kept = answer if answer is not None else prior_listing_defaults.get(key)
        if kept:
            listing_defaults[key] = kept
    return_policy = (
        answers.etsy_return_policy
        if answers.etsy_return_policy is not None
        else prior_listing_defaults.get("return_policy")
    )
    if return_policy:
        listing_defaults["return_policy"] = return_policy
    etsy["listing_defaults"] = listing_defaults

    carried = {k: v for k, v in prior.items() if k not in ASKED_TOP_LEVEL_KEYS}
    document: dict[str, Any] = {"printify": printify, "etsy": etsy}
    document.update(carried)
    return document


SHOP_YAML_HEADER = """\
# This workspace's shop-wide configuration, written by `etsy-listings setup`.
#
# Safe to edit by hand -- but a later `setup` run rewrites the file, so these
# comments are regenerated and any of your own will not survive.
#
# No credentials live here. Tokens and API keys are in .env, and the Etsy
# OAuth tokens in .auth/, both gitignored and both written by
# `etsy-listings auth`.
"""

FIELD_COMMENTS: dict[str, str] = {
    "printify": "Where products are created. `setup` reads these from your token.",
    "printify.shop_name": "the shop's name in Printify -- so the id below is checkable",
    "printify.shop_id": "every product call is scoped to this",
    "printify.preferred_print_provider": (
        "by name, not id; preselected by `new` when it offers this garment"
    ),
    "etsy": "The shop listings are published to, and the defaults every listing inherits.",
    "etsy.shop_name": "the shop's name on Etsy",
    "etsy.shop_id": "resolved from the name above",
    "etsy.currency": (
        "read from the Etsy shop; every price in this workspace must be written in it"
    ),
    "etsy.listing_defaults": (
        "every field a listing inherits -- override any of these in a listing's own etsy: block"
    ),
    "etsy.listing_defaults.who_made": (
        "i_did | someone_else | collective -- someone_else needs a production_partner below"
    ),
    "etsy.listing_defaults.when_made": "made_to_order for print-on-demand",
    "etsy.listing_defaults.is_supply": "false for a finished item",
    "etsy.listing_defaults.renewal": (
        "manual | auto -- whether a listing renews itself after four months"
    ),
    "etsy.listing_defaults.shipping_profile": (
        "by name, not id -- resolved against the shop's shipping profiles when a listing is planned"
    ),
    "etsy.listing_defaults.return_policy": (
        "by its terms, not an id -- Etsy gives the resource no title"
    ),
    "etsy.listing_defaults.production_partner": (
        "by name; omit if the shop has exactly one -- required alongside who_made: someone_else"
    ),
}
"""One line per field, in the file itself.

`shop.yaml` is the one file in a workspace people open by hand, and every
value in it is either an opaque number or a term of art from somebody's API.
A comment costs a line and saves a trip to the documentation."""


def render_shop_yaml(document: dict[str, Any]) -> str:
    """The file as written: header, then the document with a comment per field.

    Comments are woven into `safe_dump`'s output rather than templated around
    it, because the document's shape is not fixed -- optional keys come and go
    -- and a template would have to know every one of them twice.
    ``sort_keys=False`` keeps the order the document was built in, with the
    shop identifiers before the long tail of Etsy defaults.

    The dotted path a line maps to is tracked by indentation depth rather than
    by a single top-level "section", so a field nested two deep --
    ``etsy.listing_defaults.shipping_profile`` -- resolves as reliably as a
    top-level one. A stack of ``(indent, key)`` ancestors is popped back to
    whatever level the current line sits at, exactly like matching brackets.
    """
    dumped = yaml.safe_dump(document, sort_keys=False, allow_unicode=True)
    lines: list[str] = []
    ancestors: list[tuple[int, str]] = []
    for line in dumped.splitlines():
        stripped = line.strip()
        indent = len(line) - len(line.lstrip(" "))
        key = stripped.split(":", 1)[0] if ":" in stripped and not stripped.startswith("-") else ""
        path = ""
        if key:
            while ancestors and ancestors[-1][0] >= indent:
                ancestors.pop()
            path = ".".join([*(k for _, k in ancestors), key])
            ancestors.append((indent, key))
        comment = FIELD_COMMENTS.get(path)
        if comment:
            if indent == 0:
                lines.append("")
            lines.append(f"{' ' * indent}# {comment}")
        lines.append(line)
    return SHOP_YAML_HEADER + "\n".join(lines) + "\n"

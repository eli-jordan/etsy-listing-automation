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

from etsy_listings.clients.printify.models import Shop
from etsy_listings.workspace import layout

WORKSPACE_DIRS: tuple[str, ...] = (
    layout.DESIGNS_DIR,
    layout.LISTINGS_DIR,
    layout.PROFILES_DIR,
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

GITIGNORE_ENTRIES: tuple[tuple[str, str], ...] = (
    (layout.ENV_FILE, "API tokens -- never commit"),
    (f"{layout.AUTH_DIR}/", "OAuth tokens -- never commit"),
    (f"{layout.CACHE_DIR}/", "derived: catalog, renders, run history"),
)
"""What must not reach a repository, and why.

A workspace is not a git repository by default, but people put one around it
-- the listings and pricing are worth versioning. The two that would leak a
credential are the reason this file is written at all; ``.cache/`` is there
because it is large and fully derivable.
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


def update_gitignore(root: Path) -> tuple[str, ...]:
    """Append any missing entry to ``.gitignore``; return the lines added.

    Appends rather than rewrites: the file may already carry rules that have
    nothing to do with us, and a workspace's ``.gitignore`` is the user's.
    """
    path = root / ".gitignore"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    # The pattern, not the line: the entries this function writes carry a
    # trailing `# why` comment, so comparing whole lines made every run think
    # its own previous output was missing and append it again.
    present = {line.split("#", 1)[0].strip() for line in existing.splitlines()}

    added = tuple(
        f"{pattern:<12} # {why}" for pattern, why in GITIGNORE_ENTRIES if pattern not in present
    )
    if not added:
        return ()

    prefix = existing if not existing or existing.endswith("\n") else existing + "\n"
    path.write_text(prefix + "\n".join(added) + "\n", encoding="utf-8")
    return added


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


@dataclass(frozen=True)
class SetupAnswers:
    """Everything ``setup`` collects, in one value the renderer can be tested
    against without a terminal."""

    printify_shop_id: int
    currency: str
    who_made: str
    when_made: str
    is_supply: bool
    renewal: str
    preferred_print_provider: str | None
    etsy_shop_id: int | None


ASKED_ETSY_KEYS = ("shop_id", "who_made", "when_made", "is_supply", "renewal")
ASKED_TOP_LEVEL_KEYS = ("printify", "etsy", "currency", "preferred_print_provider")
"""What ``setup`` puts a question in front of the user for.

The split matters, and it is the half that is easy to get backwards. Anything
*not* named here -- ``etsy.shop_section_id`` and ``etsy.return_policy_id``
that Phase 3 fills in, plus any top-level key a later version adds -- is
carried through untouched, because dropping a value nobody was asked about is
how a re-runnable command becomes a destructive one.
"""


def shop_yaml_document(answers: SetupAnswers, existing: dict[str, Any] | None) -> dict[str, Any]:
    """The ``shop.yaml`` mapping to write, merged over whatever is there.

    Two rules, and they are complements rather than a compromise:

    - **What ``setup`` never asked about is kept**, verbatim. See
      :data:`ASKED_ETSY_KEYS`.
    - **What it did ask about, the answer wins.** Asking a question and then
      discarding the answer is worse than either overwriting or not asking:
      it silently tells the user their input does not matter. The caller seeds
      each prompt with the value already on disk, so pressing enter through a
      re-run keeps everything -- which is what makes this safe.

    ``None`` for an optional answer means "not known", never "delete it": a
    prompt seeded with a value cannot come back blank.
    """
    prior: dict[str, Any] = dict(existing or {})
    prior_etsy: dict[str, Any] = dict(prior.get("etsy") or {})
    prior_printify: dict[str, Any] = dict(prior.get("printify") or {})

    printify = {**prior_printify, "shop_id": answers.printify_shop_id}

    etsy: dict[str, Any] = {k: v for k, v in prior_etsy.items() if k not in ASKED_ETSY_KEYS}
    etsy.update(
        {
            "who_made": answers.who_made,
            "when_made": answers.when_made,
            "is_supply": answers.is_supply,
            "renewal": answers.renewal,
        }
    )
    etsy_shop_id = (
        answers.etsy_shop_id if answers.etsy_shop_id is not None else prior_etsy.get("shop_id")
    )
    if etsy_shop_id is not None:
        # Omitted rather than defaulted when unknown: a placeholder id looks
        # real enough to be published against, which is how `12345678` ended
        # up in a workspace that had no Etsy shop at all.
        etsy["shop_id"] = etsy_shop_id

    carried = {k: v for k, v in prior.items() if k not in ASKED_TOP_LEVEL_KEYS}
    document: dict[str, Any] = {"printify": printify, "etsy": etsy, "currency": answers.currency}
    if answers.preferred_print_provider:
        document["preferred_print_provider"] = answers.preferred_print_provider
    document.update(carried)
    return document


SHOP_YAML_HEADER = (
    "# Written by `etsy-listings setup`. Safe to edit by hand -- but a later\n"
    "# `setup` run rewrites this file, so its own comments will not survive.\n"
)


def render_shop_yaml(document: dict[str, Any]) -> str:
    """``sort_keys=False`` so the file reads in the order it was built, with
    the shop identifiers before the long tail of Etsy defaults."""
    return SHOP_YAML_HEADER + yaml.safe_dump(document, sort_keys=False, allow_unicode=True)


def env_with(existing: str, key: str, value: str) -> str:
    """``existing`` with ``key`` set to ``value``, everything else untouched.

    Rewriting the line in place rather than appending keeps a second
    assignment from shadowing the first, and leaves comments and unrelated
    keys exactly where the user put them. A commented-out assignment is not a
    match -- it is a note, and silently un-commenting one would be a surprise.
    """
    lines = existing.splitlines()
    prefix = f"{key}="
    replaced = False
    for index, line in enumerate(lines):
        if line.startswith(prefix):
            lines[index] = f"{key}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"

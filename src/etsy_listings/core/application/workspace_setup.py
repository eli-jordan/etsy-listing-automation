"""Configuring a workspace: what ``setup`` writes, and the rules it writes by.

The directories a workspace needs, the packaged prompts it is seeded with,
and ``shop.yaml`` -- read raw, merged with what ``setup`` asked, rendered with
a comment per field, and saved after the token that goes with it. Finding
the shops those answers name is :mod:`shop_discovery`'s; asking the questions
is the CLI's (``cli/setup.py``), the one part no test can drive cheaply.

The one rule that shapes all of it: **`setup` fills gaps, it does not
correct answers.** Re-running it on a configured workspace must be safe, so an
existing value always wins over a freshly collected one, and the ids Phase 3
fills in are never dropped. Prompts are the one opt-in exception (ADR-0044).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from etsy_listings.core.ai.brief import default_brief_prompt_text
from etsy_listings.core.ai.market_queries import default_market_queries_prompt_text
from etsy_listings.core.ai.prompt import (
    PromptSync,
    backup_path,
    default_seo_prompt_text,
    sync_prompt,
)
from etsy_listings.core.config.secrets import PRINTIFY_TOKEN_VAR
from etsy_listings.core.workspace import layout, scaffold

WORKSPACE_DIRS: tuple[str, ...] = (
    layout.DESIGNS_DIR,
    layout.LISTINGS_DIR,
    layout.GARMENT_PROFILES_DIR,
    layout.PRICING_PLANS_DIR,
    layout.MOCKUP_TEMPLATES_DIR,
    layout.COMMON_MEDIA_DIR,
    layout.COMMON_COPY_DIR,
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


POD_DEFAULTS: dict[str, Any] = {
    "who_made": "someone_else",
    "when_made": "made_to_order",
    "is_supply": False,
    "renewal": "manual",
}
"""What every print-on-demand t-shirt listing answers (ADR-0028: the shirt
genuinely was made by another company), so a wizard can offer them as one
confirmation rather than four questions.

``who_made: someone_else`` requires a production partner attached to the
listing (decision 3) -- not enforced here, since resolving a *name* to a
partner needs the shop's live list, which `setup` may not be able to reach.
`plan` is where an unresolvable or missing partner blocks."""


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
    """By name. Free text: resolving it against the shop's live list
    needs `shops_r` and a bearer, which `setup` may not have -- that
    resolution happens once per run in `EtsyShopCatalog`, at plan time."""
    etsy_return_policy: dict[str, Any] | None = None
    """The three terms (`accepts_returns`, `accepts_exchanges`,
    `within_days`), since Etsy gives the resource no title. Built
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


# ------------------------------------------------------------ packaged prompts

PACKAGED_PROMPTS: tuple[tuple[str, Callable[[], str], str], ...] = (
    (layout.SEO_PROMPT_FILE, default_seo_prompt_text, "AI SEO"),
    (layout.BRIEF_PROMPT_FILE, default_brief_prompt_text, "design brief"),
    (layout.MARKET_QUERIES_PROMPT_FILE, default_market_queries_prompt_text, "market queries"),
)
"""Every prompt `setup` ships: its file under ``prompts/``, its packaged
default, and the name a report gives it. A file in ``prompts/`` that is not
here is the seller's own and `setup` never touches it."""


@dataclass(frozen=True)
class PackagedPrompt:
    """What syncing one packaged prompt did, in workspace-relative terms."""

    where: str
    label: str
    backup: str
    """Where a replaced prompt was kept, whether or not this run replaced it --
    a ``differs`` report names it as where ``--replace-prompts`` would put it."""
    outcome: PromptSync


def sync_packaged_prompts(root: Path, *, replace: bool) -> tuple[PackagedPrompt, ...]:
    """Seed, check or replace each packaged prompt.

    `setup` fills gaps and does not correct answers; prompts are the one
    opt-in exception, because a workspace would otherwise never receive new
    instructions such as `seo.md`'s market-data rules. Without ``replace``, a
    prompt that differs from its default is left byte for byte (ADR-0044).
    """
    outcomes: list[PackagedPrompt] = []
    for filename, default_text, label in PACKAGED_PROMPTS:
        path = root / layout.PROMPTS_DIR / filename
        outcomes.append(
            PackagedPrompt(
                where=f"{layout.PROMPTS_DIR}/{filename}",
                label=label,
                backup=f"{layout.PROMPTS_DIR}/{backup_path(path).name}",
                outcome=sync_prompt(path, default_text(), replace=replace),
            )
        )
    return tuple(outcomes)


# ----------------------------------------------------------- reading and saving


def read_shop_document(root: Path) -> dict[str, Any] | None:
    """The current ``shop.yaml`` as a raw mapping, or ``None``.

    Raw rather than a parsed ``Defaults``: a workspace whose file does not
    validate is exactly the one `setup` should be able to repair, and parsing
    it first would refuse the job.
    """
    path = root / layout.SHOP_FILE
    if not path.is_file():
        return None
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else None


def save_setup(
    root: Path,
    *,
    printify_token: str,
    answers: SetupAnswers,
    existing: dict[str, Any] | None,
) -> Path:
    """Store the verified token, then write ``shop.yaml``; the file's path.

    Called once every question is answered, never before: a token left
    behind by a cancelled run is a workspace that looks configured and is not.
    ``shop.yaml`` goes last because it is the file that makes a directory a
    workspace, so writing it means "this worked".
    """
    scaffold.write_env_value(root, PRINTIFY_TOKEN_VAR, printify_token)
    path = root / layout.SHOP_FILE
    path.write_text(render_shop_yaml(shop_yaml_document(answers, existing)), encoding="utf-8")
    return path

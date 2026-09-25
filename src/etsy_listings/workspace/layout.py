"""The names of everything in a workspace tree. A8.

Only :class:`etsy_listings.workspace.workspace.Workspace` reads these -- the
rest of the codebase asks it for a path rather than joining names itself, so
this file is the single place the layout is defined.
"""

from __future__ import annotations

# Top level
SHOP_FILE = "shop.yaml"
EXCEPTIONS_FILE = "exceptions.yaml"
SETTINGS_FILE = "settings.yaml"
"""The seller's tunable settings -- today the market scoring weights
(market-seo.md, *Scoring*). Optional: absent means every default."""
ENV_FILE = ".env"
AUTH_DIR = ".auth"
ETSY_TOKENS_FILE = "etsy-tokens.json"
"""Inside :data:`AUTH_DIR`. Separate from ``.env`` because its contents are
written by this tool rather than pasted by the user, and rewritten on every
refresh (PRD 49)."""
CACHE_DIR = ".cache"
PROMPTS_DIR = "prompts"
SEO_PROMPT_FILE = "seo.md"
"""Inside :data:`PROMPTS_DIR`. Plain seller-editable instruction text the AI
SEO feature appends its delimited JSON context and response schema to
(``ai/prompt.py``) -- `setup` seeds a packaged default only when this file is
absent, and never overwrites seller content (AI SEO implementation plan,
PR3)."""
BRIEF_PROMPT_FILE = "brief.md"
"""Inside :data:`PROMPTS_DIR`, and everything said about
:data:`SEO_PROMPT_FILE` applies unchanged. This is the prompt that drafts a
listing brief from its design image when a design is attached (PRD 68); a
workspace without it can still use AI Mode by hand, so its absence disables
only the automatic draft."""
MARKET_QUERIES_PROMPT_FILE = "market-queries.md"
"""Inside :data:`PROMPTS_DIR`, seeded like the other two. The prompt that turns
a brief, a design and the garment's display title into three Etsy buyer
searches for market research (market-seo.md, *Query extraction*)."""
GARMENT_PROFILES_DIR = "garment-profiles"
PRICING_PLANS_DIR = "pricing-plans"
DESIGNS_DIR = "designs"
TEST_DESIGNS_DIR = "test-designs"
"""Calibration aids, kept apart from ``designs/``. These are throwaway targets
you judge a template's geometry and lighting against, not artwork any listing
ships -- mixing them into ``designs/`` would put non-products in the one
directory that is meant to hold only products (A19)."""
MOCKUP_TEMPLATES_DIR = "mockup-templates"
COMMON_MEDIA_DIR = "common-media"
COMMON_COPY_DIR = "common-copy"
"""Reusable `description` bodies, one Markdown file per shared paragraph
(AI SEO implementation plan). Sibling to `COMMON_MEDIA_DIR` -- both hold
content shared across listings -- but never confused with it: this directory
holds text a `description.ref` resolves to, not pictures a listing's `media:`
uploads."""
LISTINGS_DIR = "listings"

# Per listing, inside LISTINGS_DIR/<name>/
LISTING_FILE = "listing.yaml"
GENERATED_FILE = "generated.yaml"
LOCK_FILE = "state.lock.json"

# Per mockup template set, inside MOCKUP_TEMPLATES_DIR/<name>/
TEMPLATE_FILE = "template.yaml"
DERIVED_DIR = "_derived"

# Inside CACHE_DIR (gitignored, fully derivable -- PRD 22)
CATALOG_DIR = "catalog"
RENDERS_DIR = "renders"
PREVIEWS_DIR = "previews"
"""A32: full-size renders `plan` produces ahead of `apply`, content-addressed
by `scene_hash` under `PREVIEWS_DIR/<listing>/<template>/`. Sibling to
`RENDERS_DIR` rather than nested inside it -- a preview is not yet an applied
render, and `Workspace.remove_listing` needs to be able to wipe one without
the other."""
MARKET_DIR = "market"
"""Market-informed SEO's caches (market-seo.md, *Cache*), each a directory
inside it: :data:`MARKET_SEARCH_DIR` and :data:`MARKET_STATS_DIR` hold the
7-day Etsy caches, :data:`MARKET_SNAPSHOTS_DIR` the latest research per
listing (``{name}.json``), which moves and goes with the listing as
``RENDERS_DIR/<listing>`` does."""
MARKET_SEARCH_DIR = "search"
MARKET_STATS_DIR = "stats"
MARKET_SNAPSHOTS_DIR = "snapshots"
RUNS_DB = "runs.db"
FX_CACHE_FILE = "fx.json"

ROOT_ENV_VAR = "ETSY_LISTINGS_ROOT"

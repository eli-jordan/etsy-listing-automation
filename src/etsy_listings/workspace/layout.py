"""The names of everything in a workspace tree. A8.

Only :class:`etsy_listings.workspace.workspace.Workspace` reads these -- the
rest of the codebase asks it for a path rather than joining names itself, so
this file is the single place the layout is defined.
"""

from __future__ import annotations

# Top level
SHOP_FILE = "shop.yaml"
EXCEPTIONS_FILE = "exceptions.yaml"
ENV_FILE = ".env"
AUTH_DIR = ".auth"
CACHE_DIR = ".cache"
PROMPTS_DIR = "prompts"
PROFILES_DIR = "profiles"
DESIGNS_DIR = "designs"
TEST_DESIGNS_DIR = "test-designs"
"""Calibration aids, kept apart from ``designs/``. These are throwaway targets
you judge a template's geometry and lighting against, not artwork any listing
ships -- mixing them into ``designs/`` would put non-products in the one
directory that is meant to hold only products (A16)."""
MOCKUP_TEMPLATES_DIR = "mockup-templates"
COMMON_MEDIA_DIR = "common-media"
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
RUNS_DB = "runs.db"
FX_CACHE_FILE = "fx.json"

ROOT_ENV_VAR = "ETSY_LISTINGS_ROOT"

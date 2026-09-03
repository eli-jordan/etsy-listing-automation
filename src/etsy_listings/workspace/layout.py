"""Fixed paths within a workspace, relative to its root. A8."""

from __future__ import annotations

DEFAULTS_FILE = "defaults.yaml"
EXCEPTIONS_FILE = "exceptions.yaml"
ENV_FILE = ".env"
AUTH_DIR = ".auth"
CACHE_DIR = ".cache"
PROMPTS_DIR = "prompts"
PROFILES_DIR = "profiles"
DESIGNS_DIR = "designs"
MOCKUP_TEMPLATES_DIR = "mockup-templates"
COMMON_MEDIA_DIR = "common-media"
LISTINGS_DIR = "listings"

CATALOG_CACHE_DIR = f"{CACHE_DIR}/catalog"
RENDERS_CACHE_DIR = f"{CACHE_DIR}/renders"
RUNS_DB = f"{CACHE_DIR}/runs.db"
FX_CACHE_FILE = f"{CACHE_DIR}/fx.json"

ROOT_ENV_VAR = "ETSY_LISTINGS_ROOT"

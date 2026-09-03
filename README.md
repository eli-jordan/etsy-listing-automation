# etsy-listing-automation

Automates listing print-on-demand t-shirt designs on Etsy: renders custom
mockups, configures the product in Printify, and creates a reviewable Etsy
draft — idempotently, so re-running against unchanged inputs changes nothing.

**Status:** Phase 0 (foundations) is implemented — workspace discovery,
config models, the `Money` type, colour slugification, Printify catalog
fetch/cache, the `Stage`/`Change`/lockfile engine primitives, and a `plan`
skeleton. Phases 1+ (renderer, Printify, Etsy, AI copy, full UI) are not yet
built; see [docs/implementation-plan.md](docs/implementation-plan.md) for the
phase order.

## Documentation

- [Product Requirements Document](docs/prd.md) — *what* the tool does.
- [Implementation Plan](docs/implementation-plan.md) — *how* it is built.
- [Architecture](docs/architecture.md) — module boundaries and data flow, kept
  in sync with what is actually implemented.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+ (uv manages the
interpreter and virtualenv for you).

```bash
uv sync
```

This installs runtime and dev dependencies (pytest, mypy, ruff) into `.venv/`
and installs the `etsy-listings` CLI in editable mode.

Phase 1 also needs Node.js (for the calibrator's Vite/React frontend). Any
current LTS release works; nothing in the frontend build requires a specific
patch version.

## Running the CLI

```bash
uv run etsy-listings plan <listing-name>
uv run etsy-listings plan --all
```

`plan` looks for `defaults.yaml` by walking up from the current directory; pass
`--root <path>` or set `ETSY_LISTINGS_ROOT` to point at a workspace explicitly
(the *workspace* — your `defaults.yaml`, `designs/`, `listings/` — is a
separate directory you own, never this repository; see CLAUDE.md).

## Development

One command runs everything:

```bash
./scripts/check.sh
```

Or the individual steps:

```bash
uv run ruff format .          # formatter
uv run ruff check .           # linter
uv run mypy src                # strict type check
uv run pytest                  # full test suite (excludes -m e2e by default)
```

Useful pytest invocations:

```bash
uv run pytest tests/unit/test_money.py                      # one file
uv run pytest tests/unit/test_money.py::test_parses_amount_and_currency  # one test
uv run pytest -k "currency"                                   # by keyword
uv run pytest -m e2e                                           # only the (env-gated) e2e layer
uv run pytest --update-goldens                                 # regenerate render goldens (Phase 1+)
```

The `e2e` layer hits real Printify and Etsy APIs against a throwaway shop and
is never part of a default run — see CLAUDE.md and the plan's testing table
for the full five-layer split (unit / golden / behaviour / contract / e2e).

## Environment notes (Windows + cygwin git)

See [CLAUDE.md](CLAUDE.md) for the full detail — in short: this repo is edited
under cygwin/zsh but built with Windows-native Python and Node, `core.fileMode`
is deliberately `false`, and `git push`/`gh` are currently broken in this
environment (dead GitHub CLI credential helper) — commits happen locally.

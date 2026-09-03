# etsy-listing-automation

Automates listing print-on-demand t-shirt designs on Etsy: renders custom
mockups, configures the product in Printify, and creates a reviewable Etsy
draft — idempotently, so re-running against unchanged inputs changes nothing.

**Status:** Phases 0 and 1 are implemented.

- **Phase 0** — workspace discovery, config models, the `Money` type, colour
  slugification, Printify catalog fetch/cache, the `Stage`/`Change`/lockfile
  engine primitives, and a `plan` skeleton.
- **Phase 1** — the render pipeline (warp/displace/shade/export), wired into
  plan/apply as the `render` stage; a golden-test harness with synthetic
  fixtures (no real garment photography needed); a FastAPI + React calibrator
  serving live previews through the real renderer; and the `new` interactive
  garment/provider picker.

Phases 2+ (Printify, Etsy, AI copy, the rest of the UI) are not yet built; see
[docs/implementation-plan.md](docs/implementation-plan.md) for the phase
order.

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

The calibrator's frontend needs Node.js (any current LTS release):

```bash
cd src/etsy_listings/ui/frontend
npm install
```

You only need this for frontend development (`npm run dev`, below). Building
a wheel (`uv build`) runs `npm install && npm run build` for you via a
hatchling hook — see "Frontend build hook" below — and a wheel built in CI
ships `dist/` already, so *installing* the package never needs node.

## Running the CLI

```bash
uv run etsy-listings plan <listing-name>
uv run etsy-listings plan --all
uv run etsy-listings apply <listing-name>   # runs the render stage; writes state.lock.json
uv run etsy-listings new <design-name>      # interactive garment/provider picker
uv run etsy-listings ui --root <workspace>  # serves the calibrator at :8000
```

`plan`/`apply`/`new`/`ui` all look for `defaults.yaml` by walking up from the
current directory; pass `--root <path>` or set `ETSY_LISTINGS_ROOT` to point
at a workspace explicitly (the *workspace* — your `defaults.yaml`,
`designs/`, `listings/` — is a separate directory you own, never this
repository; see CLAUDE.md).

## The calibrator (Phase 1)

Templates are calibrated in a browser, against the *real* renderer:

```bash
uv run etsy-listings ui --root <workspace> --port 8000   # backend
cd src/etsy_listings/ui/frontend && npm run dev            # frontend, proxies /api to :8000
```

Open the Vite dev server's URL (default `http://localhost:5173`). Every quad
drag or slider change debounces a request to the backend, which re-renders
through the same pipeline `apply` uses and streams back a PNG — there is no
approximate/preview-only render path. "Save" writes `template.yaml`.

Frontend commands (run from `src/etsy_listings/ui/frontend/`):

```bash
npm run dev          # Vite dev server
npm run build         # production build -> dist/ (tsc -b, then vite build)
npm run typecheck     # tsc -b --noEmit, strict mode
npm run lint          # eslint .
npm run format        # prettier --write .
npm run format:check  # prettier --check .
npm run gen:api       # regenerate src/api/schema.ts from docs/openapi.json
```

After changing a FastAPI endpoint's shape, regenerate the typed client (A5:
the client is generated, never hand-written):

```bash
uv run python scripts/export_openapi.py   # writes docs/openapi.json
npm run gen:api                            # (from ui/frontend/) regenerates schema.ts
```

There's no CI in this repo yet to enforce that the committed client matches
the schema, so this is a manual step for now — remember it, or diff
`docs/openapi.json` before committing.

### Frontend build hook

`hatch_build.py` is a hatchling custom build hook: `uv build` / a fresh
editable install runs `npm install && npm run build` automatically, but only
when `ui/frontend/dist/` doesn't already exist — a CI-built wheel ships
`dist/` pre-built, so installing *that* wheel needs no node at all.

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
uv run pytest --update-goldens                                 # regenerate render goldens
```

The `e2e` layer hits real Printify and Etsy APIs against a throwaway shop and
is never part of a default run — see CLAUDE.md and the plan's testing table
for the full five-layer split (unit / golden / behaviour / contract / e2e).

No real design files or garment photography exist in this repo (or on a
fresh checkout) — golden and behaviour tests run against procedurally
generated synthetic fixtures instead (a grid/ruler test design, a tiny
two-colour mockup template set). Regenerate them with:

```bash
uv run python scripts/generate_test_assets.py
```

Deterministic (fixed seed, no clock input) — re-running should reproduce
byte-identical files.

## Environment notes (Windows + cygwin git)

See [CLAUDE.md](CLAUDE.md) for the full detail — in short: this repo is edited
under cygwin/zsh but built with Windows-native Python and Node, `core.fileMode`
is deliberately `false`, and `git push`/`gh` are currently broken in this
environment (dead GitHub CLI credential helper) — commits happen locally.

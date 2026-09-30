# etsy-listing-automation

Automates listing print-on-demand t-shirt designs on Etsy: renders custom
mockups, configures the product in Printify, and creates a reviewable Etsy
draft — idempotently, so re-running against unchanged inputs changes nothing.

## Documentation

- [Getting started](docs/getting-started.md) — a hands-on walkthrough.
- [Infrastructure setup](docs/setup.md) — the Printify and Etsy accounts and
  credentials the tool needs outside this repo.
- [Product Requirements Document](docs/prd.md) — *what* the tool does.
- [Implementation Plan](docs/implementation-plan.md) — *how* it is built.
- [Architecture](docs/architecture.md) — module boundaries, data flow and the
  invariants the code relies on.

## Setup

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12+ (uv manages the
interpreter and virtualenv for you).

```bash
uv sync
```

This installs runtime and dev dependencies into `.venv/` and the
`etsy-listings` CLI in editable mode.

Frontend development also needs Node.js (any current LTS):

```bash
cd src/etsy_listings/ui/frontend
npm install
```

Installing the package never needs node: `uv build` runs
`npm install && npm run build` via a hatchling hook (`hatch_build.py`) only
when `ui/frontend/dist/` doesn't already exist, and a wheel built in CI ships
`dist/` pre-built.

## Workspaces

The tool and your data are separate. Your **workspace** — `shop.yaml`,
`designs/`, `listings/`, `mockup-templates/` — is a directory you own, never
this repository. Commands find it by walking up from the current directory for
`shop.yaml`; pass `--root <path>` or set `ETSY_LISTINGS_ROOT` to point at one
explicitly.

## Running the CLI

```bash
uv run etsy-listings setup                  # initialise a workspace
uv run etsy-listings new                    # interactive design/garment/provider picker
uv run etsy-listings new <design-name>      # ...or name the design up front
uv run etsy-listings plan <listing-name>    # diff against live state
uv run etsy-listings plan --all
uv run etsy-listings apply <listing-name>   # execute the plan; writes state.lock.json
uv run etsy-listings ui --root <workspace>  # serves the UI at :8000
```

## The calibrator

Templates are calibrated in a browser, against the *real* renderer:

```bash
uv run etsy-listings ui --root <workspace> --port 8000   # backend
cd src/etsy_listings/ui/frontend && npm run dev            # frontend, proxies /api to :8000
```

Open the Vite dev server's URL (default `http://localhost:5173`). Every quad
drag or slider change debounces a request to the backend, which re-renders
through the same pipeline `apply` uses — there is no approximate render path.
"Save" writes `template.yaml`.

Each editor has two views of the same template:

- **Calibrate** — the draggable canvas, rendered downscaled (longest edge 900px)
  so a drag is live. Corner handles reshape the quad; hold **shift** to resize
  the whole box about the opposite corner, or **alt** to resize about its
  centre, keeping the shape. A colour-matrix set picks its working colour from
  the dropdown beside the tabs.
- **Preview** — full-size renders, exactly what `apply` will write. Opening the
  tab renders the set; changing a box afterwards does not (a twelve-colour set
  is real work), so **Re-render** turns red instead. Click any preview to open
  it large, with a 1:1 view and arrow keys to step through the set.

### Frontend commands

Run from `src/etsy_listings/ui/frontend/`:

```bash
npm run dev           # Vite dev server
npm run build         # production build -> dist/
npm run typecheck     # tsc, strict
npm run lint          # eslint
npm run format        # prettier --write (check.sh runs this)
npm run format:check  # prettier --check (CI runs this)
npm run test          # vitest
npm run test:coverage # vitest with the coverage gate
npm run gen:api       # regenerate src/api/schema.ts from docs/openapi.json
```

After changing a FastAPI endpoint's shape, regenerate the typed client — it is
generated, never hand-written:

```bash
uv run python scripts/export_openapi.py   # writes docs/openapi.json
npm run gen:api                            # from ui/frontend/
```

## Development

One command runs everything, including the coverage gates for Python and the
frontend:

```bash
./scripts/check.sh
```

Or the individual steps:

```bash
uv run ruff format .           # formatter
uv run ruff check .            # linter
uv run mypy src                # strict type check
uv run pytest                  # full suite (excludes -m e2e by default)
uv run pytest --cov            # ...with the branch-coverage gate
```

CI ([ci.yml](.github/workflows/ci.yml)) runs the same gates on pull requests,
on Ubuntu and Windows. The browser layer runs on pushes to `main`, alongside the
[e2e workflow](.github/workflows/e2e.yml).

### Tests

Branch coverage must stay at or above **85%**. It isn't on by default, so
running one file doesn't trip a gate it could never meet; the gate lives in
`check.sh`. `uv run pytest --cov --cov-report=html` then opening
`htmlcov/index.html` shows which branches are missed.

```bash
uv run pytest tests/unit/test_money.py                      # one file
uv run pytest tests/unit/test_money.py::test_parses_amount_and_currency  # one test
uv run pytest -k "currency"                                   # by keyword
uv run pytest -m browser                                       # only the browser tests
uv run pytest -m "not browser"                                 # skip them
uv run pytest --update-goldens                                 # regenerate render goldens
uv run pytest -m e2e                                           # real Printify/Etsy; see below
```

The **browser layer** drives the calibrator in real chromium via playwright
against the built SPA. It needs a one-off setup, and skips with a message naming
the missing step otherwise:

```bash
uv run playwright install chromium
cd src/etsy_listings/ui/frontend && npm run build
```

The **e2e layer** talks to the real Printify and Etsy shops and is never part of
a default run. It needs `PRINTIFY_API_TOKEN`, or `ETSY_LISTINGS_ROOT` pointing at
a workspace whose `.env` carries the credentials:

```bash
ETSY_LISTINGS_ROOT=/path/to/workspace uv run pytest -m e2e
E2E_REAL_AI=1 ETSY_LISTINGS_ROOT=/path/to/workspace uv run pytest -m e2e tests/e2e/test_ai_run_e2e.py   # with signed-in Codex/Claude
```

No real designs or garment photography live in this repo. Golden and behaviour
tests use procedurally generated fixtures; regenerate them (deterministically)
with `uv run python scripts/generate_test_assets.py`.

## Windows notes

Development happens in **zsh under cygwin**, with Windows-native `uv`, Python
and `node` on its PATH. Run commands, tests and installs there rather than in
PowerShell or Git Bash: Git Bash mangles POSIX path arguments and puts its own
`bash` ahead of cygwin's, which breaks the `npm` launcher. `git` and `gh` work
from any shell. `core.fileMode` is deliberately `false` (Windows can't hold the
exec bit), and `LF → CRLF` warnings from git are harmless.

## Contributing with AI agents

[AGENTS.md](AGENTS.md) holds the working rules for coding agents.

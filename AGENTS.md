# AGENTS.md

Automation that takes a print-on-demand t-shirt design from a file to a reviewable Etsy draft: renders mockups locally, configures the product in Printify, patches the Etsy listing. Idempotent — re-running against unchanged inputs makes no remote changes. Python 3.12+ (uv, hatchling, Typer, pydantic v2, httpx, OpenCV + Pillow, ruff, mypy, pytest) with a React + TypeScript + Vite frontend.

Check the tree or [docs/architecture.md](docs/architecture.md) before assuming a
module, command or test exists. [docs/README.md](docs/README.md) indexes current
requirements, guides, research and decisions.

## Project map

```
src/etsy_listings/
  cli/ Typer app, one module per command
  workspace/ root discovery, path resolution, the only code that knows the directory layout
  config/ pydantic models, Money, slugs, listing_validation.py (every local refusal)
  engine/ Stage protocol, Change vocabulary, lockfile, plan/apply/run, lifecycle, stages/
  render/ pure render passes, frozen RenderConfig, pipeline
  clients/ printify/ and etsy/ — transport, models, fakes
  ai/ SEO/brief providers (Codex/Claude), prompts, proposals
  market/ market-informed SEO research
  ui/ FastAPI api/ + React frontend/ (see frontend/AGENTS.md)
  newcmd/ setupcmd/ authcmd/ the `new`, `setup` and `auth` wizards
  connections.py credentials.py prompts.py terminal.py client wiring, credential steps, prompt backend, encoding guard
tests/ unit, golden, behaviour, browser, contract, e2e; shared doubles in tests/support/
docs/ guides/, features/<topic>-YYYYMMDD/, adr/, reference/, research/, history/, architecture.md
scripts/ check.sh, sloc.py, generate_test_assets.py
```

Every package's `__init__.py` states what it exports and deliberately withholds. Read that before reaching into a submodule.

The tool lives here; user data (`shop.yaml`, `designs/`, `listings/`, `mockup-templates/`, `.cache/`) lives in a separate workspace directory found by walking up from cwd for `shop.yaml` (`ADR-0013`). Never write user data into this repo or assume cwd is the workspace.

<important if="you need to run commands to build, test, lint, or generate code">

Run all of these in cygwin zsh from the repo root (see Environment).

```
uv sync # install deps + create.venv
./scripts/check.sh # format + lint + typecheck + test + coverage gate, Python and frontend
uv run pytest # full suite (excludes -m e2e by default)
uv run pytest tests/unit/test_money.py # one file
uv run pytest tests/unit/test_money.py::test_parses_amount_and_currency # one test
uv run pytest -k "currency" # by keyword
uv run pytest --cov # coverage, enforcing the 85% branch floor
uv run pytest --cov --cov-report=html # then open htmlcov/index.html
uv run pytest -m e2e # env-gated e2e layer (real shop, see Testing)
uv run pytest -m browser # playwright browser tests
uv run pytest -m "not browser" # skip them (e.g. no chromium installed)
uv run playwright install chromium # one-off, enables the browser layer
uv run pytest --update-goldens # regenerate render goldens
uv run mypy src # strict type check
uv run ruff check. / ruff format. # lint / format
uv run python scripts/sloc.py --summary # code size, prose excluded
```

Frontend (`src/etsy_listings/ui/frontend/`): `npm run dev|build|typecheck|lint|format|format:check|test|test:coverage|gen:api`. After changing a FastAPI endpoint's shape, regenerate the typed client (`ADR-0011`, never hand-written): `uv run python scripts/export_openapi.py`, then `npm run gen:api`.

Human-facing setup, calibrator usage and contributor docs live in [README.md](README.md); this file holds only what an agent needs to act correctly. Keep the two commands lists in step.

CLI surface (`etsy-listings`). `setup`, `auth`, `new`, `plan`, `apply`, `unlock` and `ui` exist in `cli/app.py`; `render`, `generate`, `catalog refresh` and `status` remain unbuilt — do not assume a command exists because a historical plan lists it.

```
setup initialise a workspace: skeleton, shop.yaml, ids
                   --replace-prompts: reset prompts/ to packaged defaults, keeping <name>.md.bak (ADR-0044)
auth every credential: Printify, Etsy key pair + OAuth, Anthropic (auth printify|etsy|anthropic)
new [<design>] interactive design/garment/provider picker; writes garment profile + listing
plan <listing|--all> three-way diff against live state
apply <listing|--all> execute every stage the plan identified
unlock <listing> clear a Printify product stuck publishing
ui dashboard, calibrator, listings, run runner
render / generate force a single local stage [not built]
catalog refresh force-refresh the cached Printify catalog [not built]
status [<listing>] run history [not built]
```
</important>

<important if="you are changing requirements, architecture decisions or documentation, or citing a decision">

[Feature specifications](docs/README.md#features) own current requirements;
[architecture](docs/architecture.md) owns current mechanism and invariants;
[ADRs](docs/adr/README.md) record decision rationale and constraints. Later
feature amendments override earlier requirements. Batch-creation interactions
override that feature's spec where they differ. The frozen documents under
`docs/history/` are context, not current authority.

Change an unworkable ADR explicitly, in its own documentation commit before
implementation. Cite `ADR-NNNN` when a choice needs its rationale; keep a
self-contained comment when it already explains the rule. New feature folders
use the date their first document was created; shipped plans stay beside the
feature with delivery PR links. See the [documentation authority rules](docs/README.md#documentation-authority).
</important>

<important if="you are running commands, installing tools, or touching paths, encodings or prompts on this Windows/cygwin machine">

**Run commands, tests, linters, mypy, `npm` and installs in cygwin zsh** — not PowerShell, `cmd` or Git Bash. Git Bash mangles POSIX arguments (`/home/Admin` → `C:/Program Files/Git/home/Admin`) and puts its own `bash` ahead of cygwin's, breaking the `npm` launcher. `git` and `gh` are the exception and work from any shell. If a command fails in cygwin zsh, that is a real failure.

The repo is `/home/Admin/code/etsy-listing-automation` in cygwin, `C:\cygwin64\home\Admin\code\etsy-listing-automation` from Windows. `uv`, Python and `node` are Windows binaries on cygwin's PATH: the working directory translates, path *arguments* do not.

- `--root` / `ETSY_LISTINGS_ROOT` accept cygwin paths and translate them (`workspace/userpath.py`), so `--root` is declared `str`, not `Path`. Any new CLI option taking a user path needs the same treatment.
- The cygwin pty is not a Windows console. prompt_toolkit cannot prompt (`NoConsoleScreenBufferError`), so all interactive prompts go through `prompts.py`'s plain-`input()` fallback — never call questionary directly. `isatty()` is False and the encoding is cp1252; `terminal.adopt_declared_encoding()` trusts `LANG`, `FORCE_COLOR` opts colour back in.
- A cygwin-only binary (e.g. `fzf`, a shebang script) is invisible to `shutil.which`. `newcmd/prompts.py` falls back to cygwin's `sh.exe`; any new external-command dependency needs the same two-step lookup.
- `core.fileMode` is false in this repo. Leave it; do not commit mode-only changes. `LF → CRLF` warnings are noise.
- Synced workspaces (Google Drive) mark directories read-only and Windows then refuses `os.rmdir`. Use `workspace.remove_tree`, not `shutil.rmtree`, for any tree this tool owns.
</important>

<important if="you are changing dependencies or versions in pyproject.toml">

- OpenCV and Pillow are **pinned to exact versions**: renders are hashed and compared to goldens, and a bump that shifts output bytes re-uploads every listing's images. Do not loosen the pins.
- Check Typer and Click compatibility together when changing either. Current
  constraints and resolved versions live in `pyproject.toml` and `uv.lock`.
- Node (any current LTS) is only needed for frontend work, not for installing the package.
</important>

<important if="you are adding or changing engine stages, hashing, rendering, workspace paths, credentials or clients, or prompts">

Read the **Invariants** section of [docs/architecture.md](docs/architecture.md) first: who may compute a diff or merge a lockfile, what may enter a hash, how a stage refuses, render purity, template kinds, path safety, credential resolution, and currency.
</important>

<important if="you are writing or modifying tests, or investigating test failures">

Layers (`ADR-0010`): unit, golden (per-pass and end-to-end renders), behaviour (in-memory fake clients), browser (`-m browser`, playwright over the built SPA), contract (cassette replay through real httpx), e2e (`-m e2e`), plus Vitest for the frontend.

- Use a **fake** to test behaviour and a **cassette** to test payload shape; do not ask either to do the other's job.
- A test file has one subject. Shared doubles live in `tests/support/` (`builders`, `scripted`, `doubles`, `http`) — look there before writing another `fake_run` closure.
- Golden failures should name the guilty render pass. Regenerate with `--update-goldens` only after looking at the diff.
- No real design files or photography in the repo; `scripts/generate_test_assets.py` generates deterministic synthetic assets.
- The browser layer runs in a normal `pytest` but skips if playwright, chromium or `ui/frontend/dist` is missing. Assert through observable effects (decoded PNG size, the `template.yaml` Save wrote), not internal state.
- `ETSY_LISTINGS_REQUIRE_EVERY_LAYER=1` turns those clean skips into failures; both `main`-tier workflows set it.
</important>

<important if="you are running or modifying the e2e tests, or the e2e workflow">

E2E hits the real Printify and Etsy APIs and is excluded by default (`addopts = "-m 'not e2e'"`). Printify tests need `PRINTIFY_API_TOKEN` or `ETSY_LISTINGS_ROOT` pointing at a workspace whose `.env` has it; market research tests need that workspace's Etsy app key. Tests skip before any network call when a prerequisite is missing.

```
ETSY_LISTINGS_ROOT=/path/to/workspace uv run pytest -m e2e
E2E_REAL_AI=1 ETSY_LISTINGS_ROOT=/path/to/workspace uv run pytest -m e2e tests/e2e/test_ai_run_e2e.py # full market AI, signed-in local providers
```

Run it locally before merging rather than iterating through CI. `gh workflow run e2e --ref <branch>` re-runs just that workflow. If CI's Etsy sign-in goes stale (refresh tokens rotate on use), run `etsy-listings auth etsy` locally and update the `ETSY_TOKENS_JSON` secret.
</important>

<important if="you are adding code that changes test coverage, or a coverage gate fails">

`./scripts/check.sh` fails under 85% **branch** coverage (`fail_under` in `pyproject.toml`); the frontend has the same floor via `npm run test:coverage`. Write the test — never lower the threshold or add `# pragma: no cover` (only genuinely unreachable code like `__main__` guards, already configured). `check.sh` runs `npm run format` (writes); CI runs `format:check`. `check.sh` skips the frontend gate when `npm` is absent.
</important>

<important if="you are changing CI workflows or scripts/check.sh">

[ci.yml](.github/workflows/ci.yml): PRs run format-check, ruff, mypy and `pytest -m "not browser"` under the coverage floor on ubuntu and windows, plus the frontend gate; pushes to `main` add `pytest -m browser`. [e2e.yml](.github/workflows/e2e.yml): `pytest -m e2e`, on push to `main` or manually. The PR tier is deliberately hermetic (no network, no browser). Windows is in the matrix because goldens were generated there; ubuntu proves the OpenCV/Pillow pins produce the same bytes. CI mirrors `check.sh` rather than calling it — change one, change the other.
</important>

<important if="you are measuring or reducing code size">

Use `scripts/sloc.py`, not physical line count: it strips blanks, comments and docstrings, because this codebase is deliberately heavy on rationale. Extracting a shared abstraction is usually LOC-neutral (the props type or protocol costs what the duplication did); judge by whether there is now one place to change the thing.
</important>

<important if="you are editing docs/history/prd.md, docs/history/implementation-plan.md or other docs">

Docs are prose with tables, not bullet soup. State a decision, then the reason it beat the alternative — rationale is what stops a decision being silently reversed. No filler, no hedging, no restating the obvious.
</important>

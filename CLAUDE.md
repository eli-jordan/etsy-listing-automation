# CLAUDE.md

Guidance for working in this repository.

## What this repo is

Automation that takes a print-on-demand t-shirt design from a file to a
reviewable Etsy draft: renders custom mockups locally, configures the product in
Printify, and patches the resulting Etsy listing. Idempotent by design — re-running
against unchanged inputs must make no remote changes.

**Phases 0 and 1 are implemented**; Phases 2-6 are not. "Code layout" below
shows what exists today, marked per module. "Commands" still describes the
PRD's full CLI surface — `plan`, `apply`, `new` and `ui` are real; the rest is
the agreed design for later phases. Check the tree, or
[docs/architecture.md](docs/architecture.md), before assuming a module,
command or test exists.

## The two documents, and which wins

| Document | Authority |
|---|---|
| [docs/prd.md](docs/prd.md) | *What* the tool does. 27 numbered product decisions in its appendix. |
| [docs/implementation-plan.md](docs/implementation-plan.md) | *How* it is built. 10 architecture decisions, `A1`–`A10`. |

When the two disagree, **the PRD wins** and the plan is wrong — fix the plan.

Both documents are settled by deliberate decision, not by drafting momentum. Do
not quietly revisit a numbered decision while implementing something adjacent to
it. If a decision turns out to be unworkable, say so and change the document
first, in its own commit.

Cite decisions by number in commit messages and in code comments where a choice
looks arbitrary without context — `# A2: lockfile stores the verbatim
last-applied doc` saves the next reader a trip through 700 lines of PRD.

## Environment

Git runs under **cygwin with zsh**. This matters more than usual here:

- Use POSIX paths and shell syntax. The repo lives at
  `/home/Admin/code/etsy-listing-automation` from inside cygwin, and at
  `C:\cygwin64\home\Admin\code\etsy-listing-automation` from Windows tools.
- The toolchain is **Windows-native, driven from cygwin**: `uv` (and the Python
  it manages) and `node` are Windows binaries on cygwin's PATH via
  `~/.zshenv`. Cygwin translates the *working directory* for them, so running
  `uv run pytest` or `npm run build` from inside the repo just works. Paths
  passed as *arguments* do not translate — `C:\...` is what those binaries see.
- `--root` and `ETSY_LISTINGS_ROOT` therefore accept cygwin paths and translate
  them (`workspace/userpath.py`): `/home/Admin/ws`, `/cygdrive/c/ws` and
  `C:\ws` all work. This is why `--root` is declared `str`, not `Path` — on
  Windows `str(Path("/home/Admin"))` is already `\home\Admin`, and a mangled
  path can't be distinguished from a root-relative one. Any *new* CLI option
  taking a user-supplied path needs the same treatment.
- `core.fileMode` is set to **false** in this repo's local config. The Windows
  filesystem cannot hold the exec bit, so without it every checkout shows phantom
  `100755 → 100644` modifications on files that were committed from elsewhere.
  Leave it off; do not commit mode-only changes.
- Line endings: git warns about `LF → CRLF` on write. Content is stored LF. The
  warnings are noise, not a problem to fix.

### Known-broken: GitHub credentials

`~/.gitconfig` routes GitHub HTTPS auth through GitHub CLI:

```
credential.https://github.com.helper !'/cygdrive/c/Program Files/GitHub CLI/gh.exe' auth git-credential
```

That path does not exist — `gh` is not installed. Consequences: **`git push`,
`git ls-remote` and anything else touching `origin` will hang** on the dead
helper (it blocks rather than failing fast), and `gh` commands are unavailable, so
PRs cannot be opened from the command line.

Diagnose quickly with `GIT_TERMINAL_PROMPT=0 git ls-remote origin` — that fails
fast instead of hanging. Fix is the user's call: reinstall GitHub CLI, or delete
the two stale `credential.https://*.github.com.helper` lines from `~/.gitconfig`
so git falls back to `manager-core`.

Until it is fixed, commit locally and tell the user the push and PR could not be
done. Do not silently skip the step.

## Toolchain

uv + `pyproject.toml`, Python 3.12+, `src/` layout, hatchling, Typer, pydantic v2,
httpx, OpenCV + Pillow, ruff, pytest. Frontend is React + TypeScript built with
Vite, living under `src/etsy_listings/ui/frontend/`.

OpenCV and Pillow are **pinned to exact versions**, deliberately. Renders are
hashed and compared against goldens; a minor bump that shifts output bytes causes
every listing's images to re-upload. Do not loosen those pins casually.

`click` is pinned to `<8.2` alongside typer `0.12.x` — a newer click breaks
typer's `TyperArgument.make_metavar()` call signature. Bump both together if
you ever upgrade typer.

Node is only needed for frontend development, not for installing the package
(see "Frontend build hook" in the README) — any current LTS works. On a
machine without admin rights (`winget install` needing elevation fails), the
official Windows x64 zip from nodejs.org extracts and runs fine from a
user-writable directory with no installer.

## Code layout

Per `A1`–`A10`. Full detail in the plan; the shape:

```
src/etsy_listings/
  cli/          Typer app, one module per command        [plan/apply/new/ui done]
  workspace/    root discovery (walk up for defaults.yaml), path resolution  [done]
  config/       pydantic models, Money type, slugification     [done]
  catalog/      Printify catalog fetch + TTL cache + name-to-id resolution  [done]
  engine/       Stage protocol, Change vocabulary, lockfile, plan, apply, stages/
                                        [done; STAGES = [Render()], more stages later]
  render/       pure passes, frozen RenderConfig, derived maps, pipeline    [done]
  newcmd/       `new` picker: pure logic + a thin questionary wrapper       [done]
  clients/      printify/ and etsy/: protocol, http, models, fakes; limiter, retry
                                                                            [Phase 2/3]
  ai/           prompts, generation, hard validation                      [Phase 4]
  runs/         SQLite recorder                                           [Phase 6]
  ui/           FastAPI api/ (calibrator endpoints) + React frontend/      [done]
                             (dashboard/setup wizard/run runner: Phase 5)
```

## Invariants

These are the things that are easy to break by accident and expensive to notice
later. Each traces to a decision.

- **Only `engine` computes a diff.** The CLI renderer and the UI serialiser both
  consume `Plan` / `StagePlan` / `Change` objects. Neither may compare states
  itself — that is what makes the CLI and UI enforce identical rules (`A2`, PRD 20).
- **Nothing volatile enters a hash.** No timestamps, no absolute paths, no model
  output, no `tool_version`. Only the lockfile's `applied` subtree is hashed, via
  the single `canonical_hash()` helper. Violating this makes every run show a
  spurious diff.
- **Paths inside hashed content are workspace-relative and forward-slashed.**
  Non-negotiable on Windows, where the same content would otherwise hash
  differently than on Linux.
- **Render passes are pure.** No I/O, no globals, no clock. Inputs are ndarrays
  and frozen config. This is what makes both the hash and the goldens meaningful
  (`A7`).
- **Every `cv2` call passes explicit `interpolation` and `borderMode`.** Relying
  on defaults makes output depend on the library version.
- **`Workspace.resolve()` rejects paths escaping the root** (`A8`). This is also
  what keeps the UI's file endpoints safe, so it is a security boundary, not a
  tidiness rule.
- **Two hash axes, not one.** `input_hash` decides whether to re-render;
  `outputs` (per-file) decides whether to re-upload. Collapsing them breaks the
  library-upgrade case the PRD calls out.
- **Every price carries an explicit currency.** Bare numbers are rejected at
  validation. Revenue is NOK, Printify's costs are USD; a bare number is a bug
  waiting to be a refund (PRD 24).
- **Mockup filename = slugified Printify colour name.** Convention, not a mapping
  table. A sparse `exceptions.yaml` handles what will not slugify (PRD 7a).
- **`apply` is strictly sequential; only `plan`'s read-only live fetches fan out**
  over a thread pool (`A3`). Never parallelise writes.
- **Secrets never enter the repo.** Tokens in `.auth/`, keys in `.env`, both
  gitignored, and both in the *workspace*, not here.

## Workspace vs repo

This repository is the **tool**. The data — `defaults.yaml`, `designs/`,
`listings/`, `mockup-templates/`, `.cache/` — lives in a separate directory the
user owns, found by walking up from cwd for `defaults.yaml` (`A8`). Never write
user data into this repo, and never assume cwd is the workspace root.

## Testing

Five layers, each with a job (`A4`):

| Layer | Job |
|---|---|
| Unit | slugification, `Money`, hash canonicalisation, path resolution, limiter maths |
| Golden | per-pass renders on a grid target; end-to-end composites per template |
| Behaviour | in-memory fake clients: idempotency, drift, resume, polling, batch |
| Contract | cassette replay through real httpx: payload shape, auth, error decoding |
| E2E | `-m e2e`, skipped by default, env-gated at a throwaway shop |

Reach for a **fake** to test behaviour and a **cassette** to test payload shape.
Asking either to do the other's job is the mistake this split exists to prevent.

Golden failures should name the guilty render pass — that is why per-pass goldens
exist alongside end-to-end ones. Regenerate with `--update-goldens` only after
looking at the diff.

No real design files or garment photography live in this repo (or a fresh
checkout) — `scripts/generate_test_assets.py` procedurally generates a
grid/ruler test design and a tiny synthetic mockup template set, deterministically
(fixed seed, no clock input), committed as ordinary test fixtures.

The E2E test hits real Printify and Etsy and costs real state. It is never part of
a default run. It also doubles as the cassette recorder.

### Running the suite

```
uv sync                              # install deps + create .venv
./scripts/check.sh                   # format + lint + typecheck + test, one command
uv run pytest                        # full suite (excludes -m e2e by default)
uv run pytest tests/unit/test_money.py                     # one file
uv run pytest tests/unit/test_money.py::test_parses_amount_and_currency  # one test
uv run pytest -k "currency"          # by keyword
uv run pytest -m e2e                 # only the env-gated e2e layer
uv run pytest --update-goldens       # regenerate render goldens (Phase 1+)
uv run mypy src                      # strict type check
uv run ruff check . / ruff format .  # lint / format
```

Frontend (`src/etsy_listings/ui/frontend/`): `npm run dev|build|typecheck|lint|format`.
See the README's "The calibrator" section for the full loop, including
regenerating the typed API client after an endpoint change.

## Commands

`plan`, `apply`, `new` and `ui` are implemented. The rest of this table is the
PRD's agreed CLI surface for reference when building later phases — do not
assume a command exists because it is listed here.

```
new <design>       interactive garment/provider picker; writes profile + listing   [done]
plan <listing|--all>   three-way diff against live state                          [done]
apply <listing|--all>  execute every stage the plan identified          [done; only `render` exists]
render / generate      force a single local stage                    [render: via apply; generate: Phase 4]
ui                     setup wizard, dashboard, calibrator, run runner    [calibrator done; rest Phase 5]
auth                   Etsy OAuth PKCE + Anthropic credentials                     [Phase 3]
catalog refresh        force-refresh the cached Printify catalog                  [Phase 6]
unlock <listing>       clear a Printify product stuck publishing                  [Phase 2]
status [<listing>]                                                                [Phase 6]
```

## Writing style for the docs

Both documents are prose with tables, not bullet soup. They state a decision, then
the reason it beat the alternative. Rationale is the valuable part — it is what
stops a decision being silently reversed six months later. Match that register
when editing them: no filler, no hedging, no restating the obvious.

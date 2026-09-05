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

**Run everything in zsh under cygwin.** Commands, test runs, linters, the type
checker, git, `npm`, and tool installs all belong in that shell — it is the
environment this project is developed and verified in, and the only one its
paths, PATH setup and scripts are known to work in. Do not reach for
PowerShell, `cmd`, or Git Bash: Git Bash in particular *looks* like it works
and then bites. It mangles POSIX arguments (`/home/Admin` becomes
`C:/Program Files/Git/home/Admin`); it puts its own `bash` ahead of cygwin's,
which breaks the `npm` launcher script; and — worst of the three, because it
hangs instead of erroring — its git cannot resolve the cygwin-style credential
helper, so anything touching `origin` blocks until something kills it (see
"GitHub access"). If a command is worth running, run it in cygwin zsh; if it
fails there, that is a real failure, not an artefact.

### The cygwin pty is not a Windows console

Two consequences, both verified under a real pty (`script -q -c ... /dev/null`),
not merely inferred from a redirect:

- **prompt_toolkit cannot prompt at all.** On `sys.platform == "win32"` it
  only ever builds a Win32/Windows-10-VT100/ConEmu output, and a cygwin pty is
  a named pipe with no console screen buffer, so `create_output()` raises
  `NoConsoleScreenBufferError` before a key is read. Anything interactive
  (questionary, `rich.prompt`) therefore needs a fallback that goes through
  plain `input()` — `newcmd/prompts.py` is the one that exists, and any new
  prompt belongs behind it rather than calling questionary directly.
- **`sys.stdout.isatty()` is False**, and the encoding is cp1252 — Python
  reads the *console codepage*, and there is no console, so the answer
  describes nothing about the terminal on the other end. mintty is UTF-8 and
  says so in `LANG`, which is why `main()` calls
  `terminal.adopt_declared_encoding()`: it believes the shell's declared locale
  over the codepage, so ⭐ and the `apply` swatches print as themselves.
  `PYTHONIOENCODING` still wins if set. `etsy_listings/terminal.py` remains
  the guard for streams that genuinely cannot print a decoration, and
  `FORCE_COLOR` opts colour back in past the `isatty()` check.
- **A cygwin-only binary is invisible to `shutil.which`.** cygwin's `fzf` is
  `/usr/bin/fzf`, a shebang script with no `.exe`; native-Windows Python can
  neither find nor exec it. `newcmd/prompts.py` falls back to asking cygwin's
  `sh.exe` (located beside `cygpath.exe`, the trick `workspace/userpath.py`
  already uses) and runs the tool through it. Any future dependency on an
  external command needs the same two-step lookup.

The repo lives at `/home/Admin/code/etsy-listing-automation` from inside
cygwin, and at `C:\cygwin64\home\Admin\code\etsy-listing-automation` from
Windows tools. Use POSIX paths and shell syntax.
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

### GitHub access — use cygwin git, and only cygwin git

Working, as of GitHub CLI 2.98.0. `~/.gitconfig` routes GitHub HTTPS auth
through `gh`:

```
credential.https://github.com.helper !'/cygdrive/c/Program Files/GitHub CLI/gh.exe' auth git-credential
```

`git push`, `git fetch` and `gh pr create` all work — **from cygwin zsh**,
where `git` is `/usr/bin/git`.

That helper path is a **cygwin** path. Only cygwin's git can resolve it. Run
git from Git Bash (`/mingw64/bin/git`) and the helper cannot be found, but git
does not report that: the command **hangs** until something kills it, and then
reports

```
fatal: helper error (143): Unknown
```

143 is SIGTERM — the exit code of whatever killed it, not a diagnosis. This
looks exactly like a missing `gh.exe`, and previously *was* one, so it is easy
to misread as "GitHub access is broken" and go hunting for an install that is
already there.

**If anything touching `origin` hangs, check which git you are running before
anything else** (`which git` — it must be `/usr/bin/git`). This is the sharpest
instance of the general rule above: run everything in cygwin zsh.

To distinguish a genuine auth failure from the wrong-git hang:
`GIT_TERMINAL_PROMPT=0 git ls-remote origin` fails fast on real auth problems,
and `gh auth status` confirms the account and scopes independently of git.

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
  workspace/    root discovery (walk up for shop.yaml), path resolution  [done]
  config/       pydantic models, Money type, slugification     [done]
  catalog/      Printify catalog fetch + TTL cache + name-to-id resolution  [done]
  engine/       Stage protocol, Change vocabulary, lockfile, plan, apply, stages/
                                        [done; STAGES = [Render()], more stages later]
  render/       pure passes, frozen RenderConfig, derived maps, pipeline    [done]
  newcmd/       `new` picker: pure logic + a thin prompt wrapper              [done]
  clients/      printify/ and etsy/: protocol, http, models, fakes; limiter, retry
                                                                            [Phase 2/3]
  ai/           prompts, generation, hard validation                      [Phase 4]
  runs/         SQLite recorder                                           [Phase 6]
  ui/           FastAPI api/ (calibrator endpoints) + React frontend/      [done]
                             (dashboard/setup wizard/run runner: Phase 5)
  terminal.py   stdlib-only leaf: can this stream print that character?     [done]
```

Every package's `__init__.py` states its interface — what it exports and what
it deliberately withholds. Read that before reaching into a submodule; if what
you need isn't exported, that is usually the docstring telling you why.

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
- **Only `workspace` knows the directory layout.** Everything else asks for
  `workspace.lock_file(name)` rather than joining
  `listings/<name>/state.lock.json`. Two rules enforce it: `resolve()` rejects
  paths escaping the root (`A8`), and the layout accessors reject any name that
  is not a single path segment. Together they are what keeps the UI's endpoints
  safe — template names arrive from URLs — so this is a security boundary, not
  a tidiness rule. A new path-taking CLI option or endpoint goes through them.
- **Two hash axes, not one.** `input_hash` decides whether to re-render;
  `outputs` (per-file) decides whether to re-upload. Collapsing them breaks the
  library-upgrade case the PRD calls out.
- **Every price carries an explicit currency.** Bare numbers are rejected at
  validation. Revenue is NOK, Printify's costs are USD; a bare number is a bug
  waiting to be a refund (PRD 24).
- **`colour-matrix`-kind mockup filename = slugified Printify colour name.**
  Convention, not a mapping table. A sparse `exceptions.yaml` handles what
  will not slugify (PRD 7a). `multiple`- and `single`-kind templates use a
  fixed `scene.png` instead — no per-colour photo to name (PRD 28).
- **A template is exactly one of three kinds — never a mix.** `kind:
  colour-matrix | multiple | single`, a discriminated union (`A11`). **No
  profile-level registry of templates** — `Profile` carries no `templates`
  field; a template lives purely in `mockup-templates/{name}/`, and any
  listing may reference any of them. A listing's `media:` always names
  `{template, colour?}` explicitly — there is no default template and no
  bare-colour shorthand (`A13`, PRD 29).
- **Rendering is driven purely by `media`.** A scene renders only if some
  `media` entry references it — `listing.colors` drives which Printify
  variants sell (Phase 2), not which photos get rendered (PRD 31).
- **`apply` is strictly sequential; only `plan`'s read-only live fetches fan out**
  over a thread pool (`A3`). Never parallelise writes.
- **Secrets never enter the repo.** Tokens in `.auth/`, keys in `.env`, both
  gitignored, and both in the *workspace*, not here. `config/secrets.py` is the
  only reader; a missing credential is reported by name and file, never as a
  raw `401` traceback. Resolve tokens lazily — `plan` builds a catalog client
  it never calls, and demanding a token there breaks every workspace that
  hasn't needed one yet.
- **`plan` checks two things, not one: would the output differ, and is the
  output still there.** The render cache is gitignored and fully derivable, so
  it is a directory users delete. A stage's `read_live()` is called even when
  `local` is true — `local` means "no *remote* state", so no drift reporting
  and no thread-pool fan-out, not "reads nothing" (`A1`).

## Workspace vs repo

This repository is the **tool**. The data — `shop.yaml`, `designs/`,
`listings/`, `mockup-templates/`, `.cache/` — lives in a separate directory the
user owns, found by walking up from cwd for `shop.yaml` (`A8`). Never write
user data into this repo, and never assume cwd is the workspace root.

## Testing

Six pytest layers, each with a job (`A4`, plus `browser` added in Phase 1),
plus a separate frontend unit layer:

| Layer | Job |
|---|---|
| Unit | slugification, `Money`, hash canonicalisation, path resolution, limiter maths |
| Golden | per-pass renders on a grid target; end-to-end composites per template |
| Behaviour | in-memory fake clients: idempotency, drift, resume, polling, batch |
| Browser | `-m browser`, playwright over the built SPA served by FastAPI: one full drag → render → save loop per template kind |
| Contract | cassette replay through real httpx: payload shape, auth, error decoding |
| E2E | `-m e2e`, skipped by default, env-gated at a throwaway shop |
| Frontend unit (Vitest) | `ui/frontend/`, not part of `pytest` — component tests for the calibrator's editors, panels and API client; `npm run test` / `test:coverage` |

The browser layer runs as part of a normal `pytest` (unlike `e2e`) but skips
itself cleanly when playwright, its chromium build, or `ui/frontend/dist` is
missing. It exists for the one thing no other layer covers: that the React app,
the FastAPI endpoints and the real renderer work *together*. Assertions go
through observable effects — a PNG the browser actually decoded at the
template's true pixel size, and the `template.yaml` that Save wrote to disk —
not through internal state.

Reach for a **fake** to test behaviour and a **cassette** to test payload shape.
Asking either to do the other's job is the mistake this split exists to prevent.

Golden failures should name the guilty render pass — that is why per-pass goldens
exist alongside end-to-end ones. Regenerate with `--update-goldens` only after
looking at the diff.

No real design files or garment photography live in this repo (or a fresh
checkout) — `scripts/generate_test_assets.py` procedurally generates a
grid/ruler test design and a tiny synthetic mockup template set, deterministically
(fixed seed, no clock input), committed as ordinary test fixtures.

The E2E layer talks to the real Printify API. It is never part of a default run
(`addopts = "-m 'not e2e'"`), and it skips cleanly — every test, no network at
all — unless the machine has credentials: `PRINTIFY_API_TOKEN`, or
`ETSY_LISTINGS_ROOT` pointing at a workspace whose `.env` carries it.

```
ETSY_LISTINGS_ROOT=/path/to/workspace uv run pytest -m e2e
```

Phase 1's e2e tests are **read-only** catalog GETs, so they cost no state and
can be re-run freely. Their job is that the contract layer's transcripts are
photographs nobody re-takes: if Printify moves a field, every offline test
stays green and the failure surfaces as a user's `new` run falling over
instead. The e2e layer asks the live API the questions the offline suite
answers from memory. The write-side tests that genuinely do cost state arrive
with Phase 2, against a throwaway shop.

### Coverage: 85% is a floor, not a target

`./scripts/check.sh` measures **branch** coverage over the whole suite and
**fails under 85%** (`fail_under` in `pyproject.toml`). Line coverage is not
enough: a half-tested `if` is the shape most regressions hide in.

It currently sits at ~93%, so there is real headroom. If a change drops it
below the floor, that change shipped untested logic — write the test. Do not
lower the threshold, and do not add `# pragma: no cover` to make a number go
up. The one legitimate use of an exclusion is code that genuinely cannot be
exercised in-process (a `__main__` guard, a `TYPE_CHECKING` block), and those
are already configured centrally.

Coverage is deliberately **not** in `addopts`, so running one file
(`uv run pytest tests/unit/test_money.py`) doesn't fail a gate it was never
going to meet. The gate lives in the check script, which is what runs before a
commit.

**The frontend carries a matching gate** — Vitest + the v8 coverage provider,
same 85%-branch floor, same "not in the default `npm run test`" reasoning
(`npm run test:coverage` is the enforced one). `./scripts/check.sh` runs both
gates and skips the frontend one cleanly (not a failure) when `npm` isn't on
`PATH`, so a Python-only contributor's `check.sh` run isn't blocked by a
toolchain they don't have.

### Running the suite

All of these run in cygwin zsh (see Environment).

```
uv sync                              # install deps + create .venv
./scripts/check.sh                   # format + lint + typecheck + test + coverage gate, Python and frontend
uv run pytest --cov                  # coverage on demand, enforcing the 85% floor
uv run pytest --cov --cov-report=html  # then open htmlcov/index.html
uv run pytest                        # full suite (excludes -m e2e by default)
uv run pytest tests/unit/test_money.py                     # one file
uv run pytest tests/unit/test_money.py::test_parses_amount_and_currency  # one test
uv run pytest -k "currency"          # by keyword
uv run pytest -m e2e                 # only the env-gated e2e layer
uv run pytest -m browser             # only the calibrator browser tests
uv run pytest -m "not browser"       # skip them (e.g. no chromium installed)
uv run playwright install chromium   # one-off, enables the browser layer
uv run pytest --update-goldens       # regenerate render goldens
uv run mypy src                      # strict type check
uv run ruff check . / ruff format .  # lint / format
```

Frontend (`src/etsy_listings/ui/frontend/`):
`npm run dev|build|typecheck|lint|format|test|test:coverage`. See the
README's "The calibrator" section for the full loop, including regenerating
the typed API client after an endpoint change.

### CI

[`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs the same gates,
split in two by what a layer needs from the outside world.

| Trigger | What runs |
|---|---|
| Pull request | `ruff format --check`, `ruff check`, `mypy`, `pytest -m "not browser"` under the 85% floor, on **ubuntu and windows**; plus the frontend's eslint/tsc/vitest gate |
| Push to `main` | all of the above, then `pytest -m browser` and `pytest -m e2e` |

The PR tier is deliberately hermetic — unit, golden, behaviour and contract
touch no network and no browser, so a PR cannot go red on somebody else's
infrastructure. The `browser` and `e2e` layers need chromium and a real
Printify token respectively, so they sit on `main`, where the token lives as
the repository secret `PRINTIFY_API_TOKEN`. Phase 1's e2e tests are read-only
catalog GETs, so running them on every push costs no state.

Windows is in the matrix because it is where development happens and where the
render goldens were generated; ubuntu is there to prove the exact OpenCV and
Pillow pins really do produce the same bytes on both, rather than assuming it.

CI mirrors `scripts/check.sh` rather than calling it — that script is bash and
reformats in place. Change one, change the other.

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

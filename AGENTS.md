
Guidance for working in this repository.

## What this repo is

Automation that takes a print-on-demand t-shirt design from a file to a
reviewable Etsy draft: renders custom mockups locally, configures the product in
Printify, and patches the resulting Etsy listing. Idempotent by design — re-running
against unchanged inputs must make no remote changes.

**Phases 0, 1 and 2 are implemented**; Phases 3-6 are not. "Code layout" below
shows what exists today, marked per module. "Commands" still describes the
PRD's full CLI surface — `setup`, `plan`, `apply`, `new` and `ui` are real; the
rest is the agreed design for later phases. Check the tree, or
[docs/architecture.md](docs/architecture.md), before assuming a module,
command or test exists.

## The two documents, and which wins

| Document | Authority |
|---|---|
| [docs/prd.md](docs/prd.md) | *What* the tool does. 70 numbered product decisions in its appendix. |
| [docs/implementation-plan.md](docs/implementation-plan.md) | *How* it is built. 28 architecture decisions, `A1`–`A28`. |

Four subsidiary documents carry detail those two point at rather than repeat:
[docs/multi-placement-rendering.md](docs/multi-placement-rendering.md) (PRD 28),
[docs/phase-3-etsy.md](docs/phase-3-etsy.md) (PRD 52–59, A24–A28),
[docs/listing-lifecycle.md](docs/listing-lifecycle.md) (PRD 61–67), and
[docs/deploy-changes.md](docs/deploy-changes.md) (PRD 20's runner, A29–A33). They are
not a third authority — where any disagrees with the PRD, the PRD wins.

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
checker, `npm`, and tool installs all belong in that shell — it is the
environment this project is developed and verified in, and the only one its
paths, PATH setup and scripts are known to work in. Do not reach for
PowerShell, `cmd`, or Git Bash for those: Git Bash in particular *looks* like
it works and then bites. It mangles POSIX arguments (`/home/Admin` becomes
`C:/Program Files/Git/home/Admin`), and it puts its own `bash` ahead of
cygwin's, which breaks the `npm` launcher script. Git and `gh` are the
exception — they work from PowerShell and Git Bash; `~/.gitconfig` routes
GitHub HTTPS auth through `gh.exe` with a Windows path, so they do not need
cygwin. If a command is worth running, run it in cygwin zsh; if it fails
there, that is a real failure, not an artefact.

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
- **A directory can arrive read-only, and Windows then refuses to delete it.**
  Anything syncing a workspace — Google Drive is the one that found this — sets
  `FILE_ATTRIBUTE_READONLY` on every directory, and `os.rmdir` answers a bare
  `WinError 5` while the files inside delete fine. `workspace.remove_tree` is
  the `shutil.rmtree` that clears the flag and retries; use it rather than
  `shutil.rmtree` for any tree this tool owns.

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

Per `A1`–`A23`. Full detail in the plan; the shape:

```
src/etsy_listings/
  cli/          Typer app, one module per command  [setup/plan/apply/new/ui done]
  workspace/    root discovery (walk up for shop.yaml), path resolution  [done]
                facts.py — the garment profiles and template configs a listing
                  check reads, gathered once per request instead of re-parsed
                  inside every check of every row
                common_copy.py — `common-copy/*.md` front-matter parsing, pure;
                  `Workspace.load_common_copy`/`compose_description` are the
                  I/O and the one shared resolver around it (AI SEO plan PR2)
  config/       pydantic models, Money type, slugification     [done]
                description.py — `etsy.description`'s lead/text/ref model and
                  the pure `compose_description(lead, text)` join rule every
                  deployment reader shares (AI SEO plan PR2)
                listing_validation.py — every reason a listing cannot run, as
                  far as its own files can tell. One module, two readers: the
                  editor's issues banner and (through `engine/stages/gates.py`)
                  every stage
  engine/       Stage protocol, Change vocabulary, lockfile, plan, apply, run,
                  lifecycle (PRD 61–67), preview (A32), stages/
                   [done; STAGES = [Render(), PrintifyProduct(), Publish(),
                   EtsyListing(), EtsyMedia()], Generate() in Phase 4]
                stages/ splits the product stage three ways: the stage itself
                  (needs a context), product_document (the two documents and
                  the garment gate) and product_diff (the comparison — pure,
                  and unit-tested without a workspace or a fake)
                stages/ also holds what belongs to no single stage: gates (the
                  stage's adapter over `config/listing_validation.py` — same
                  three names, a `Blocked` instead of an `Issue`), etsy_target (which
                  listing on which shop — the id key, the shop gate, one
                  not-minted error, shared by all three Etsy stages) and
                  colour_property (Etsy's inventory property matched onto this
                  listing's colours — pure, same reasoning as product_diff)
  render/       pure passes, frozen RenderConfig, derived maps, pipeline    [done]
  newcmd/       `new` picker: pure logic + a thin prompt wrapper              [done]
  setupcmd/     `setup`: workspace init, token verification, shop discovery  [done]
  authcmd/      `auth`: the credential command, per part (PRD 14, 49, 50)    [done]
  clients/      printify/ — one package for everything said to Printify (A22):
                  transport (token/retry/errors), two protocols (CatalogClient
                  reads, PrintifyClient writes), models, catalog, products,
                  cache, resolve, fakes                                      [done]
                etsy/ and limiter Phase 3/6; retry.py done
  ai/           request/task/proposal contracts, the two packaged default
                prompts, delimited-context assembly, hard validation, the
                Codex/Claude adapters and the chain over them  [done]
                A provider takes a `ProviderTask` -- assembled prompt text, a
                  response schema, one image -- and knows nothing about which
                  feature asked, so SEO generation and brief drafting (PRD 68)
                  share one fallback order, one repair rule and one deadline
                brief.py -- everything drafting-specific in one small module:
                  request, schema, packaged prompt, validation
  runs/         SQLite recorder                                           [Phase 6]
  ui/           FastAPI api/ (calibrator + listings endpoints) + React     [done]
                frontend/ -- AppShell/DashboardPage/ListingsPage/
                ListingEditorPage (design strip + Variants/Images/Details
                tabs, and the create form too: it mounts at /listings/new on
                an empty draft, where naming it is what writes it) done;
                setup wizard and run runner remain, Phase 5
                frontend/src/media.ts — what `media:` holds and what it looks
                  like: every picture URL and every ref→name derivation, for
                  both halves of the app
                frontend/src/pages/editor/ — the Images tab is four modules:
                  MediaLocator (browse and add), MediaReel (order, by drag),
                  focus (what the preview points at) and mediaEdits (what a
                  click *changes* — pure, PRD 56's swatch gate included)
  prompts.py    which prompt backend can drive this terminal at all, and the
                cancel-raising wrappers the wizards ask through              [done]
  credentials.py  one credential step — where it already lives, the blurb, the
                ask, the caller's verification, the refusal. Shared by `setup`
                and `auth`; capturing stays separate from storing             [done]
  connections.py  what a workspace can talk to: the transports, the token
                store, the clients and the RunContext, with every credential
                resolved lazily. Verifying one is `credentials.py`'s          [done]
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
- **Only `engine` runs a run.** The same rule, one level up: reading a
  listing's lockfile, planning it, executing it, writing the lockfile back and
  carrying on past a failure (PRD 16) all live in `engine/run.py`, behind
  `plan_listings` / `apply_listings`. An entry point supplies the listings and
  formats the resulting `RunReport`; it never opens a lockfile itself.
- **Only the lockfile merges a lockfile.** `Lockfile.fold()` owns the
  replace-versus-merge rules for all four axes, `applied_for()` owns the
  per-stage lookup and `parse_applied_for()` owns the decode. A stage returns
  a `StageApplyResult` and never touches the file; `execute` decides only
  which stages run, in what order.
- **A stage's applied document is a type, not a dict — and the stage does not
  decode it.** The lockfile stores it as JSON; `build_plan` hands `plan()` the
  model the stage declared in `applied_model` (`RenderApplied`,
  `AppliedProduct`). A stage that reads its own document with
  `applied.get("title")` ends up spelling the key names again in every
  function that touches them — that is where a `("?", "?")` fallback for a
  lookup that cannot miss came from. Decoding answers `None` for both "never
  applied" and "will not decode", because a document we cannot read is one we
  cannot prove the live state matches. **Every question a stage is asked gets
  it**, `apply()` included — the one that did not have it went and decoded its
  own subtree, which is a second implementation of a rule that exists to have
  one. (It took the place of a `stage_plan` parameter no stage read: three
  `del`'d it and the protocol had already drifted, one stage typing it
  `object` while the rest said `StagePlan`.) That rule is the lockfile's precisely
  because it was two stages' and they disagreed: one caught `ValidationError`
  and answered `None`, the other indexed the dict and raised `KeyError`, which
  is not a `UserFacingError` and so ended a whole `--all` batch.
- **A refusal is `Blocked`, whichever question produced it.** One vocabulary for
  "this cannot run", reaching the plan two ways because a refusal has two
  moments. A **pre-flight** refusal — no shop configured, copy still a
  sentinel, a design too small — is `desired()` returning `Blocked`, before a
  document exists for a run that was never going to happen. A refusal only the
  live state can prove — a retail price below Printify's cost, which needs
  `variants[].cost` and therefore cannot be known before `read_live` (PRD 40's
  amendment) — is `plan()` returning `Verdict.refused(...)`, which the engine
  turns into the same `StagePlan.blocked`. Neither may raise, and a stage still
  never names itself. What is forbidden is the third shape: a stage that will
  not run reporting a `reason` instead. That is what shipped first, and
  `format_plan` prints a reason only for stages that *do* run — so a listing
  priced under cost skipped `publish` in silence, under a plan reading "No
  changes." The vocabulary exists to make exactly that impossible.
- **One rule behind that vocabulary, not one per reader.** `config/listing_validation.py`
  owns every local refusal about a listing — predicate, message and all — and
  `engine/stages/gates.py` is the adapter that turns one into a `Blocked` for a
  stage, exactly as `Issue`'s tab and severity turn one into a line in the
  editor's banner. One vocabulary with two implementations behind it is not one
  vocabulary: these were two modules, and the garment-profile rule had already
  diverged — `.strip()` on the engine's side, a bare truth test on the editor's,
  so a `garment_profile: " "` passed `plan` and failed the banner about the same
  file. A new local refusal is a check function there and nothing else.
- **A check reads the workspace through `WorkspaceFacts`, gathered once.**
  `check_listing` is pure and takes no workspace, so somebody has to open the
  files it checks against — and when that was each caller's own business,
  `_describe` parsed one garment profile twice and every listings-table row
  re-parsed the entire template catalogue. Build one where a request begins and
  hand it down; never load a profile or a template config beside a check.
- **`will_run` is derived from a reason, never computed beside one.** They were
  two expressions of one rule — `was is None or bool(changes) or live is None`
  standing next to a three-branch string — and two expressions of one rule are
  how a stage comes to run while reporting nothing to do.
- **A client is built through `connections.py`.** Which credential is resolved
  when, what a missing one means, and where the Etsy token file lives are one
  set of answers, not four. `cli`, `setup`, `auth` and the e2e layer each wrote
  out the same five-step Etsy assembly — read the `.env`, decide whether there
  is a key pair, open the token store with a refresh that can find the
  keystring again, hang a transport off it, wrap it in a client — and the e2e
  copy was the one nobody would remember to update, since it only runs where
  there are real credentials. The rule the module exists to hold: **a
  credential is resolved when it is used, never when a client is built**, so a
  workspace that has only ever rendered mockups can still `plan`.
- **A credential is captured, verified and stored through `credentials.py`.**
  Where it already lives (environment, then the workspace `.env`), what to say
  before asking, how to ask, how to prove it, and what to say when it fails.
  `setup` and `auth` each wrote that out longhand and the copies had already
  drifted: the same blurb byte-for-byte, and a refusal differing by one word.
  Capturing stays separate from storing because the two commands genuinely
  disagree about *when* — `auth` writes per credential as it goes, `setup`
  writes once every question is answered.
- **A hashed document must not depend on the order its inputs happened to
  arrive in.** Sort anything that lands in one. Variant ids reached
  `print_areas[].variant_ids` in the order a listing wrote `colors:`, so
  reordering that list changed `input_hash` and re-applied a product nothing
  about which had changed.
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
- **Only `workspace` knows the directory layout — including how to *list* one.**
  Everything else asks for `workspace.lock_file(name)` rather than joining
  `listings/<name>/state.lock.json`, and for `workspace.template_photos(name)`
  rather than globbing `mockup-templates/<name>/*.png`. Two rules enforce it:
  `resolve()` rejects paths escaping the root (`A8`), and the layout accessors
  reject any name that is not a single path segment. Together they are what
  keeps the UI's endpoints safe — template names arrive from URLs — so this is
  a security boundary, not a tidiness rule. A new path-taking CLI option or
  endpoint goes through them, and so does a new `glob`: the calibrator grew
  four private helpers that each globbed a template directory a different way,
  which is exactly the drift this rule exists to prevent.
- **A cancelled prompt raises; it is never a `None` a caller might miss.**
  `prompts.choose`/`text`/`confirm` answer `None` because that is the honest
  shape for a backend, but no wizard uses them directly — `pick`, `ask_choice`,
  `ask_text` and `ask_confirm` raise `prompts.Cancelled`, caught once in
  `cli/app.py`. A rule applied at every call site is one that will eventually
  be missed at a call site, and a missed one here writes a `None` to a file.
- **Two hash axes, not one.** `input_hash` decides whether to re-render;
  `outputs` (per-file) decides whether to re-upload. Collapsing them breaks the
  library-upgrade case the PRD calls out.
- **Every price carries an explicit currency.** Bare numbers are rejected at
  validation. Revenue is NOK, Printify's costs are USD; a bare number is a bug
  waiting to be a refund (PRD 24).
- **`colour-matrix`-kind mockup filename = slugified Printify colour name.**
  Convention, not a mapping table. A sparse `exceptions.yaml` handles what
  will not slugify (PRD 7a). When nothing matches exactly, `template_base_image`
  falls back to a filename ending in the slug's hyphen segments — but only if
  exactly one photo in the directory qualifies; two candidates is refused, not
  guessed at. That fallback is lookup-only: `template_colours` still reports
  a non-matching filename as its own name, since deriving a colour from an
  unknown shared prefix (the enumeration direction) isn't the same question as
  matching a known slug against one (the lookup direction). `multiple`- and `single`-kind templates use a
  fixed `scene.png` instead — no per-colour photo to name (PRD 28).
  **The browser is never told this rule**; it is served the answer.
  `TemplateSummary.photos` carries each scene's real workspace-relative path,
  resolved through `Workspace.scene_photo`, because the editor's caption used
  to compose one from the convention and so named a missing file for exactly
  the pack `template_base_image`'s fallback exists for.
- **A template is exactly one of three kinds — never a mix.** `kind:
  colour-matrix | multiple | single`, a discriminated union (`A11`). **No
  garment-profile-level registry of listing templates** — a template lives
  purely in `mockup-templates/{name}/`, and any listing may reference any of
  them. A listing's `media:` always names `{template, colour?}` explicitly —
  there is no default template and no bare-colour shorthand (`A13`, PRD 29).
  `GarmentProfile.preview_template` is the one exception: a single
  `colour-matrix` template the editor uses to judge colours, not a `media:`
  default.
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
| Unit | slugification, `Money`, hash canonicalisation, path resolution, limiter maths, which prompt backend runs, what a terminal can print |
| Golden | per-pass renders on a grid target; end-to-end composites per template |
| Behaviour | in-memory fake clients: idempotency, drift, resume, polling, batch |
| Browser | `-m browser`, playwright over the built SPA served by FastAPI: one full drag → render → save loop per template kind, plus a listings create → edit → autosave loop |
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

**A test file has one subject.** `tests/behaviour/test_new_prompts.py` had
three — prompt-backend selection, terminal encoding, and an end-to-end `new`
run — so a cygwin-encoding regression and a wizard regression arrived from the
same place, and two thirds of a 543-line "behaviour" file needed neither a
workspace nor a fake. It is now `tests/unit/test_prompts.py`,
`tests/unit/test_terminal.py` and `tests/behaviour/test_new.py`, with the
row-building tests folded into `test_new_picker.py` beside the rest of
`newcmd.logic`.

`tests/support/` holds what more than one file needs: `builders` (a lockfile,
a run context, an edited fixture workspace), `scripted` (the prompt double
that answers a wizard by the *text* of the question, not its position),
`doubles` (a `subprocess.run` and an `input()` stand-in — one level below
`scripted`: that replaces the prompt, these replace what the prompt calls) and
`http` (a `Transport` over an httpx mock handler, sleep always stubbed). Reach
there before writing a fourth `fake_run` closure.

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

That clean skip is right on a contributor's machine and wrong in CI, where a
layer that runs nothing still reports green.
`ETSY_LISTINGS_REQUIRE_EVERY_LAYER=1` turns every such skip — this layer's
missing token, the browser layer's missing chromium or unbuilt SPA — into a
failure naming the prerequisite. Both `main`-tier workflows set it.

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

Prettier is wired in the same way ruff is: `check.sh` runs `npm run format`,
which writes, and CI runs `npm run format:check`, which reports. `gen:api`
formats its own output, so regenerating the typed client cannot fail the gate.

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
uv run python scripts/sloc.py --summary   # code size, prose excluded
```

`scripts/sloc.py` exists because physical line count is the wrong measure
here. This codebase is deliberately heavy on rationale — the writing rules
below ask for it — so a "make it smaller" pass measured in physical lines
scores its biggest wins by deleting the most valuable text. The script strips
blank lines, comments and docstrings and counts what is left, split four ways
(`src`, `tests`, `frontend`, `frontend tests`), so a refactoring registers only
when logic actually disappears.

It is a measuring tool, not a gate, and it is worth knowing what it will not
tell you: extracting a shared abstraction is usually **LOC-neutral**, because
the interface it needs — a props type, a protocol, a dataclass, a fixture
signature — costs about what the duplicated bodies did. Three copies of forty
lines of JSX cost 120; one shell with a typed props interface costs 125. Judge
those on whether there is now one place to change the thing, not on the
number.

Frontend (`src/etsy_listings/ui/frontend/`):
`npm run dev|build|typecheck|lint|format|test|test:coverage`. See the
README's "The calibrator" section for the full loop, including regenerating
the typed API client after an endpoint change.

### CI

**Two workflows.** [`.github/workflows/ci.yml`](.github/workflows/ci.yml) runs
the same gates as `check.sh`, split by what a layer needs from the outside
world; [`.github/workflows/e2e.yml`](.github/workflows/e2e.yml) is the e2e
layer alone.

| Workflow | Trigger | What runs |
|---|---|---|
| CI | Pull request | `ruff format --check`, `ruff check`, `mypy`, `pytest -m "not browser"` under the 85% floor, on **ubuntu and windows**; plus the frontend's prettier/eslint/tsc/vitest gate |
| CI | Push to `main` | all of the above, then `pytest -m browser` |
| CI | Manual (`workflow_dispatch`) | the same as a push to `main`, against whichever ref you pick |
| e2e | Push to `main`, or manual | `pytest -m e2e` against the real Printify and Etsy shops |

The PR tier is deliberately hermetic — unit, golden, behaviour and contract
touch no network and no browser, so a PR cannot go red on somebody else's
infrastructure. The `browser` and `e2e` layers need chromium and real
credentials respectively, so they run on `main`, where the secrets live
(`PRINTIFY_API_TOKEN`, `ETSY_KEYSTRING`, `ETSY_SHARED_SECRET`,
`ETSY_TOKENS_JSON`).

`e2e` is a separate workflow because it is the one layer worth running on its
own: `gh workflow run e2e --ref <branch>` re-runs it without re-running lint,
both test matrices and the browser layer. That matters because its Etsy
sign-in expires — Etsy rotates the refresh token on every use and the CI
workspace is thrown away, so `ETSY_TOKENS_JSON` eventually goes stale and is
fixed by running `etsy-listings auth etsy` locally, updating the secret, and
re-running just this. The cost of the split is that it no longer sits behind
the lint and offline-suite gate; that is accepted, since a gate blocking the
manual re-run would be worse.

Run it locally before merging rather than iterating through CI — it is far
faster, and it costs the same real shop state either way:

```
ETSY_LISTINGS_ROOT=/path/to/workspace uv run pytest -m e2e
```

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
setup              initialise a workspace: skeleton, shop.yaml, ids   [done; its token
                   capture moves to `auth` in Phase 3 — PRD 49]
new [<design>]     interactive design/garment/provider picker; writes garment profile + listing  [done]
plan <listing|--all>   three-way diff against live state                          [done]
apply <listing|--all>  execute every stage the plan identified   [done; render + printify]
render / generate      force a single local stage                    [render: via apply; generate: Phase 4]
ui                     setup wizard, dashboard, calibrator, listings, run runner
                       [calibrator + dashboard + listings list/editor done;
                       setup wizard and run runner remain, Phase 5]
auth                   every credential: Printify, Etsy key pair + OAuth, Anthropic [Phase 3]
catalog refresh        force-refresh the cached Printify catalog                  [Phase 6]
unlock <listing>       clear a Printify product stuck publishing                  [Phase 2]
status [<listing>]                                                                [Phase 6]
```

## Writing style for the docs

Both documents are prose with tables, not bullet soup. They state a decision, then
the reason it beat the alternative. Rationale is the valuable part — it is what
stops a decision being silently reversed six months later. Match that register
when editing them: no filler, no hedging, no restating the obvious.

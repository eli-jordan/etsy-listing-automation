# Module structure implementation plan

Status: planned; no implementation PRs created. Design confirmed 2026-09-30.

The [specification](spec.md) owns the accepted requirements. This plan delivers
them as a linear stack of reviewable PRs. [ADR-0052](../../adr/0052-separate-core-from-transport-adapters.md)
records the architectural choice; existing behaviour decisions remain in force
unless the specification explicitly amends them.

The result is a transport-independent core with directly testable application
operations, a server responsible for HTTP hosting, a CLI responsible for
terminal interaction and an npm project at `src/ui`. This is more than a
package rename: rules currently embedded in routes, workers and wizards must
be accessible through focused interfaces that hide their coordination.

## Delivery and review rules

Each PR targets the preceding branch and must be usable and verifiable at its
own head. Merge bottom-up, rebase descendants when a lower layer changes and
record delivery links in the table below. Register every created PR with the
thread's PR-linking tool when available. A branch depending on the whole stack
being merged before it can build is not an acceptable intermediate state.

Keep mechanical relocation distinct from behavioural extraction. Temporary
old locations are allowed only for code not yet migrated; they are not
compatibility shims or new public interfaces. Relocated modules have one
implementation and their callers move with them. Import Linter contracts grow
as areas become clean; every temporary exclusion names its removing PR and is
gone by PR 11. Do not silently synchronize contracts to admit an unwanted
dependency.

The stack is linear for review, even where implementation could proceed
independently. Split a large workflow PR further if needed while retaining its
stated success criteria and dependency order. No layer adds commands, changes
payloads, introduces new concurrency or fixes unrelated audit findings.

| PR | Scope | Depends on | Delivery |
|---|---|---|---|
| 1 | Accepted requirements, ADR and documentation authority | — | Pending |
| 2 | Remove the native host; make `ui` HTTP-only | 1 | Pending |
| 3 | Move React/npm to `src/ui` and preserve asset packaging | 2 | Pending |
| 4 | Move foundational backend modules into core | 3 | Pending |
| 5 | Move the HTTP host into server; establish import checks | 4 | Pending |
| 6 | Extract shared listing operations and creation logic | 5 | Pending |
| 7 | Extract template, calibration and batch operations | 6 | Pending |
| 8 | Move deployment coordination into core | 7 | Pending |
| 9 | Move AI coordination, readiness and proposal operations into core | 8 | Pending |
| 10 | Separate CLI wizards from reusable setup/auth/new operations | 9 | Pending |
| 11 | Reorganize Python tests and complete interface enforcement | 10 | Pending |
| 12 | Reconcile architecture and prove installed end-to-end wiring | 11 | Pending |

## PR 1: Record the accepted design before implementation

Publish this plan, the specification and ADR-0052, index them in
`docs/README.md` and `docs/adr/README.md`, and add a pending-transition pointer
to architecture. Do not replace the current architecture with an unimplemented
target. The specification explicitly governs changed ownership and native-host
behaviour, while the plan remains sequencing rather than requirement authority.

Success means a reader can distinguish accepted design from implemented state,
find all three documents through the indexes, and identify the only intentional
user-visible change and the lack of old-import compatibility. ADR assessment
must name preserved decisions and the procedure for an actual conflict.
Review Markdown links and the agreed scope; this documentation-only PR needs
no application test run.

## PR 2: Remove the native host

Replace native-window startup with foreground uvicorn serving through the
existing app factory. Keep `etsy-listings ui`, workspace discovery, host/port
options and defaults. Delete `--browser` and `--debug`, pywebview, native window
and daemon-server helpers, and native-only tests. Update `pyproject.toml` and
`uv.lock` together, letting resolution remove only dependencies no longer needed.
Keep a small HTTP startup function that can later become the server launcher.

Success means the bare `ui` command invokes HTTP hosting without importing a
GUI toolkit, removed flags are rejected by Typer, and help describes the new
behaviour. ASGI lifespan still sweeps staging and starts/stops deployment, batch
and AI work in the existing order. A foreground shutdown retains the existing
in-flight apply/plan semantics. Update README, guides, current architecture and
agent instructions that otherwise describe a native window or removed flags.

Verify CLI argument handling with the existing `test_ui_command.py` subject,
adapt relevant lifecycle tests and run the existing non-GUI server checks.
Native-only tests are removed, not rewritten to test implementation details.

## PR 3: Relocate the npm project and preserve wheel assets

Move the whole frontend project from `src/etsy_listings/ui/frontend` to
`src/ui`, including its lockfile, design resources, local instructions, Vitest
configuration and colocated tests. Update all executable paths in
`hatch_build.py`, `pyproject.toml`, `.gitignore`, both workflows, check scripts,
browser fixtures and client generation. `gen:api` reads `../../docs/openapi.json`
from the new npm root. Update current contributor documentation and commands
with the same change.

Map `src/ui/dist` into a Python-package asset directory at wheel-build time;
do not rely on source-checkout paths at runtime or ship node_modules. Until
PR 5 moves the Python host, that directory may be `etsy_listings/ui/static`;
PR 5 moves the mapping and runtime locator to `etsy_listings/server/static`.
Resolve assets correctly for both editable development and an installed wheel.
Keep release rebuilds from `npm ci`, editable reuse, and the existing warning
when npm/assets are unavailable for Python-only development. Ensure an sdist
includes frontend source, lockfile and build hook so it can build the same wheel.

Success means no active build/test script uses the former npm directory;
Vitest, typecheck, lint, format and production build work from `src/ui`; browser
tests serve that build. The wheel test proves stale dist content is rebuilt
from current source. A wheel installed outside the checkout serves index and
referenced assets without Node or access to repository source. Gitignored build
output stays untracked, and Python-only editable behaviour remains supported.

Use the existing `tests/unit/test_wheel_frontend.py` as the packaging test
subject, extend it for mapping/source-distribution failures as needed, and run
the browser layer with prerequisites required. Updating paths alone must not
change the generated HTTP schema or TypeScript client semantics.

## PR 4: Move foundational backend modules into core

Relocate `engine`, `workspace`, `render`, `clients`, `config`, `ai`, `market`,
`batches` and `listing_templates` beneath `core`, together with shared client
construction and transport-independent errors. Update production imports,
tests, packaged prompt/resource paths and package interfaces in the same PR.
Keep package metadata at the Python root. Terminal helpers, mixed credential
capture and wizard sequencing remain outside core until their logic is split.

Success means every moved module has one new location with no forwarding
packages. Core import paths neither eagerly load FastAPI/Typer nor depend on
the old UI or wizard adapters. Engine remains the sole deployment-diff and
lockfile owner, workspace the sole layout owner, and rendering stays pure.
Resource loading works from the installed package. Existing hash, golden,
idempotency and partial-apply assertions pass unchanged in meaning.

Review this as mechanical moves plus necessary import/resource updates. Run
the hermetic Python suite and type/lint gates, including packaged-prompt tests;
do not regenerate goldens to accommodate a package move.

## PR 5: Establish server ownership and executable contracts

Move `ui/api` to `server/api`, and relocate Python hosting, static resources
and HTTP-oriented cache helpers under server. Move remaining old UI workers
temporarily under server unchanged; PRs 8 and 9 extract their application
ownership. Update app imports, OpenAPI export, browser fixtures, asset mapping
and startup so the only CLI-to-server import is in a dedicated CLI `ui` launcher.
Make `cli/app.py` register that command without importing server itself.

Add Import Linter as a development dependency with a locked resolution. Run
`uv run lint-imports` in `scripts/check.sh` and the Python CI matrix. The initial
contracts forbid core dependencies on adapters and framework/prompt modules,
forbid server-to-CLI dependencies, and restrict CLI-to-server access to the
startup interface. Package initializers must not make ordinary CLI imports
transitively load server. Construct the server app through injected core
factories and retain a lightweight CLI registration path.

Check core/server prohibitions transitively. For the CLI launcher, allow only
the specific import edge from the dedicated `cli.ui` module to server startup;
command registration may reach that edge indirectly. Do not configure a broad
CLI-versus-server independence contract that rejects this intentional path,
and do not exempt the entire CLI package. Keep the server import inside launch
execution so registering CLI commands does not eagerly load FastAPI.

Success means no Python `etsy_listings.ui` implementation remains, the server
factory still exposes the same routes, and startup/installed assets work at
the new paths. Import contracts pass on Windows and Linux and reject a
representative forbidden direct and indirect import in an isolated fixture.
No broad adapter exception is needed; application work temporarily housed in
server never creates a core-to-server dependency. Regenerate OpenAPI/client
from code and compare contracts with the pre-migration baseline, preserving
component identities where renames would otherwise change generated types.

## PR 6: Extract listing operations

Extract listing reads and coordinated edits, creation, rename, deletion and
related batch/proposal effects from `server/api/listings.py` into focused
`core/application` modules. Move shared pricing and listing creation helpers
currently imported from `newcmd.logic` behind appropriate core interfaces,
updating both route and CLI callers. Domain status and validation remain in
their established modules; do not duplicate them in a listing facade.

Core operations take application inputs and dependencies and return domain
results or typed refusals. They own lock acquisition around read/merge/write
and re-check existence under the lock. Server retains request decoding,
response projection and status choices, including invalid editor input that
currently returns HTTP 200 with field errors and unchanged listing content.
Until PRs 8 and 9 relocate locks and coordinators, inject the existing objects
through small core-owned interfaces; core must never import their temporary
server implementation. Keep those interfaces only where the dependency varies
or the transport separation requires them.

Success means tests can exercise creation/edit/rename/delete without
`TestClient` or `CliRunner`; invalid and incomplete drafts retain their existing
distinct behaviour. Tests cover competing writes, rename interactions, refusal
on published deletion and coordinated proposal/batch effects. HTTP contract
tests preserve payloads and status codes, and creation paths share one pricing
and persistence interpretation without server-to-CLI imports.

Move substantive scenarios from listing API tests to direct operation tests
where appropriate, retaining adapter cases for parsing, mapping and wire shape.
Use existing shared builders/fakes rather than reproducing entire suites at
both entry points.

## PR 7: Extract template, calibration and batch operations

Extract template configuration mapping and persistence, listing-template
capture, batch review/confirmation/retry and non-HTTP readiness/read operations
from their route modules. Reuse existing `batches`, `listing_templates`,
workspace and render interfaces. Uploaded bytes and filenames may enter core;
FastAPI UploadFile, Request and Response objects may not. Business archive
limits and safety rules stay with batch operations; HTTP upload decoding stays
with the server. Inventory design, media, settings and picker endpoints too:
retain simple adapters, and extract only application rules or coordination.

Keep browser-preview decode caches, HTTP media encoding and thumbnail response
handling in server. Core rendering still accepts images/config rather than
mutable request caches. Remote-state batching/memoization may remain server
read infrastructure where its lifetime is request-serving; application logic
receives facts through an injectable query interface.

Success means template saves and batch creation/retry can be tested directly,
archive containment/size refusals are unchanged, frozen template capture and
name allocation remain atomic/idempotent, and preview/render goldens are
unchanged. Calibrator browser tests verify decoded output dimensions and saved
template content. Template/batch HTTP contract tests preserve upload, refusal
and response behaviour; no operation knows HTTP or joins workspace paths itself.

## PR 8: Move deployment coordination into core

Move deployment registry, FIFO executor, workspace locks, reviewed workspace
apply validation and application event models into focused application modules.
The engine still computes plans/fingerprints and executes stages. Server
translates requests into commands, projects results and frames SSE. Core owns
event buffering, identity, retention and blocking event waits; SSE reconnect
headers, framing and disconnect polling belong to server.

Separate application events from wire-only schema dependencies without
introducing duplicate representations when a model is already
transport-independent. The server lifespan starts/stops an injected coordinator;
core construction must not spawn threads or require an ASGI app. Preserve the
existing deploy-to-AI handoff through a core callback/interface until PR 9 moves
its implementation, avoiding an import back into server.

Success means direct tests exercise conflicts, exact reviewed-set/fingerprint
refusals, ordered execution, retention and cancellation. Apply stays
non-cancellable; planning stops at the same safe points. Closing an SSE
connection does not cancel work, and replay after Last-Event-ID preserves
events and ordering. Shutdown preserves partial progress and creates no new
work. Existing deploy/browser scenarios pass without wire changes or a second
execution path (ADR-0037, ADR-0039 through ADR-0042).

## PR 9: Move AI coordination and proposal operations into core

Move AI registry/runner, batch dispatcher, readiness checks, deploy precedence
and proposal acceptance/dismissal/staleness operations into application modules.
Remove the current runner/event dependencies on API schemas and SEO route
helpers. Core owns provider selection and readiness meaning; server maps
results, constructs dependencies and manages coordinator lifetime. Shared locks
and stores have one instance per application runtime rather than one per route.

Success means direct tests prove one active AI run per listing, pending-batch
refusal, deploy precedence, batch concurrency/round-robin behaviour, cancellation
of provider subprocesses and interrupted-row recovery. Proposals persist before
events, retain existing acceptance/staleness semantics and clear only under
existing rules. AI/deploy/batch shutdown ordering remains unchanged. HTTP/SSE
contracts and browser reattachment pass; CLI apply still does not manipulate
the server queue (ADR-0048 through ADR-0050).

Readiness and proposal behaviour must be callable without a Request or a
running server. Do not replace the existing thread model with async execution,
add persistence for transient runs or claim cross-process coordination.

## PR 10: Separate CLI sequencing from reusable wizard operations

Move auth/new/setup prompt sequencing under CLI and extract reusable garment,
configuration, credential verification/storage and discovery operations into
core. Split `credentials.py` rather than moving its Typer output and prompts
into core. Move `prompts.py` and `terminal.py` under CLI, preserving the plain
input fallback, cancellation handling and declared-encoding guard. Complete
remaining CLI callers of shared creation/credential/setup operations.

Success means no command-labelled logic remains outside CLI/core, and core
credential operations can be tested with injected clients without terminal
interaction. Existing wizard prompts, defaults, exit behaviour, secret
precedence, auth-per-credential persistence and setup cancellation/write timing
remain intact. Auth/setup still work before shop.yaml exists; user paths still
translate correctly on Cygwin. `plan`, `apply` and `unlock` preserve their
reports/effects and use existing core interfaces without needless wrappers.

Run direct operation tests and CLI behaviour tests separately. OAuth consent
and callback handling remain credential workflow concerns, not the application
server or a new dependency from core to CLI. Terminal presentation of a required
human step belongs to CLI (ADR-0025 through ADR-0027).

## PR 11: Reorganize tests and complete interface enforcement

Move Python tests by the subject they exercise, then by existing layer. Core
gets engine/workspace/render/client/application tests; server gets HTTP/SSE and
hosting tests; CLI gets command/prompt/terminal tests. Keep shared browser/e2e,
support and fixture roots. Place truly project-wide build/CI subjects directly
under tests rather than inventing ownership. Move layer-specific conftest files
with their subjects and preserve fixture discovery, golden lookup and cassette
references, including e2e reuse of contract transcripts. TypeScript tests stay
colocated in `src/ui`.

Finalize protected implementation contracts around migrated operation modules,
using module-level public interfaces rather than a core-wide export facade.
Public declarations are documented in each package `__init__.py`; tests may
exercise internal seams within their owning module, while operation behaviour
tests and production callers use the same external interface. Ensure checks
cover the production import graph and deliberately scoped test imports rather
than accidentally permitting tests to certify an implementation-only interface.

Success means every retained Python test is collected in the intended layer,
markers/skip guards still work, no temporary import exclusions remain, and
representative forbidden dependencies/protected-module bypasses fail the gate.
The CLI launcher's exception is limited to startup. All application logic has
left server routes and terminal adapters, with documented request-serving
infrastructure retained where appropriate. Compare collection inventories
before and after moves to distinguish deliberate test replacement/native
deletion from accidental loss. Both coverage floors remain 85% branch coverage.

## PR 12: Reconcile architecture and verify the complete application

Audit the final code and replace outdated ownership, diagrams, paths and
runtime descriptions throughout `docs/architecture.md`. Update the module
table, dependency graph, calibrator flow/cache placement, run and AI lifecycle,
credential/prompt split, client construction, test ownership, enforcement and
frontend build/asset distribution. Remove native-host descriptions and state
the intentional launcher exception and preserved process-local limitations.
Retain engine/hash/render/path/currency invariants with their new module paths.

The new specification and ADR-0052 override conflicting old ownership claims;
do not preserve an outdated sentence as an alternative architecture. Update
README, current guides, reference, agent project maps/command lists and active
feature descriptions that still give obsolete paths or host behaviour. Shipped
plans and frozen history remain historical; search results there are not a
reason to rewrite delivery history. Mark the new plan/spec/ADR implementation
status accurately, remove architecture's pending-transition pointer and add
every delivery PR link to this plan.

Success means architecture describes the actual final tree and interfaces,
all executable references use new locations, no compatibility shims or native
dependency remain, and docs agree on launch behaviour and module ownership.
Run the full local gate, required browser layer and production npm build.
Verify release-wheel/source-distribution construction and install/serve from
outside the checkout without Node, then verify editable and Python-only
development paths. Run the existing credential-gated e2e suite locally before
merging code changes; report missing prerequisites as unverified, not passing.
No e2e checks run as part of writing this plan.

## Validation contract for the stack

Run implementation commands in Cygwin zsh from this worktree's repo root, not
the unrelated main checkout. `./scripts/check.sh` is the required code-change
gate; CI must mirror changed scripts, including Import Linter. Focused tests
establish the changed behaviour before the full gate. Do not lower coverage,
loosen OpenCV/Pillow pins, regenerate unexplained goldens or put user data in
the repo to make relocation pass.

| Evidence | Requirement |
|---|---|
| Direct operations | Meaningful read/write/refusal/coordination scenarios without CLI or HTTP invocation; inject shared fakes |
| Adapter contracts | Preserve requests, response codes/payloads, event unions, ids and replay semantics; generate OpenAPI/TS from code |
| Engine/render | Existing hashes, idempotency, fingerprints, resume behaviour and synthetic render goldens unchanged |
| Python gate | Ruff, strict mypy, Import Linter after introduction, full applicable pytest suite and 85% branch floor |
| Frontend gate | Format/lint/typecheck/Vitest with 85% branch floor, plus production build from src/ui |
| Browser | Install Chromium/build SPA and require the layer to run; verify visible effects and reload/replay |
| Distribution | Current assets rebuilt in wheel, source inputs in sdist, no checkout/Node dependency after install, editable fallback preserved |
| Real services | Existing env-gated e2e locally before merge; do not change credentials or workflow secrets to mask an unavailable prerequisite |

Regenerate via `uv run python scripts/export_openapi.py` followed by
`npm run gen:api` in `src/ui` when schema ownership/endpoint shape changes.
Compare generated output to the established contract; do not hand-edit it.
File moves may change generated metadata but must not casually rename public
schema components or conceal a wire change as a relocation.

## ADR assessment and documentation precedence

ADR-0052 is warranted because application ownership and dependency direction
are expensive to reverse once callers/tests depend on the shared interfaces;
the design rejects credible alternatives with different effect, packaging and
enforcement costs. Exact path spelling, ownership-first tests, removal of the
unused native shell and using Import Linter each need clear requirements and
rationale, but do not warrant separate ADRs.

| Existing decision | Effect of this work |
|---|---|
| ADR-0010 | Preserve fake/contract/e2e responsibilities while moving directories |
| ADR-0011 | Preserve generated OpenAPI/TypeScript contract; update tooling paths |
| ADR-0012, ADR-0013, ADR-0046 | Preserve render purity/pins and workspace layout/path ownership |
| ADR-0025 through ADR-0027 | Preserve auth/setup responsibilities and OAuth storage; split terminal presentation from reusable operations |
| ADR-0037 through ADR-0042 | Preserve partial-apply recording, fingerprints, previews, run resources and exact reviewed sets; relocate policy into core |
| ADR-0047 through ADR-0051 | Preserve staging/snapshots, dispatch, proposals, deploy precedence and upload safety; server remains their runtime host |

None of these records currently needs replacement: their behavioural decisions
survive the move, and server-side does not require implementation in a server
package. ADR-0052 clarifies ownership without claiming that CLI acquires the
server queue. If an implementation slice finds a genuine conflicting ADR,
amend that record explicitly, preserve its original rationale/history and land
the amendment as its own documentation commit before implementation. A plan
paragraph alone cannot silently overrule an ADR or feature requirement.

Completion requires the specification, architecture and ADRs to agree, not
merely a final paragraph saying that new decisions take precedence. PR 12 is
mandatory and the stack is unfinished until its documentation and verification
criteria are met.

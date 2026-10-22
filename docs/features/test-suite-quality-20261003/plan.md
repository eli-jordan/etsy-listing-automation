# Test suite quality implementation plan

Status: planned; no implementation PRs have been opened.

This plan delivers the [specification](spec.md) through the repository's
[implement-stack skill](../../../.claude/skills/implement-stack/SKILL.md).
The [interaction companion](interactions.md), [mockup references](mockups.md)
and [complete audit map](coverage-map.md) are execution inputs. The source
[audit](../../../reports/test-suite-audit.html) has 22 ranked groups; its
deletion table and supporting notes contribute additional assigned work.

The result is a suite with stronger independent oracles, smaller setup,
controlled scheduling and rule matrices below expensive boundaries. Valuable
integration witnesses remain. Runtime improvements are measured after changes,
not inferred from fewer files or assumed percentages.

## Stack and ownership

Use one isolated worktree and background implementer per PR. Each branch
starts at the preceding PR's reported build tip and targets that branch; PR 1
targets the recorded stack base branch. Merge bottom-up. After a build report,
freeze that branch against rewrites, start the next builder, then continue the
same agent as finisher. Finishing adds commits only. Propagate lower fixes and
updated tips according to the skill; never launch a replacement agent over an
existing worktree after an interruption.

Register every created or worked PR immediately with `link_pull_request` when
the thread tool is available. Before finishing, use `list_thread_pull_requests`
to check every layer, not just the top PR. Report a linking failure explicitly.

The planning package is committed before execution, outside the 14
implementation PRs. Include these five documents, the docs index, the linked
HTML audit, its six research/audit Markdown notes and telemetry artifacts using
explicit paths. Do not stage unrelated generated caches or use `git add .`.
That documentation commit's full SHA is the **stack base**; record it in
`execution.md` before launching PR 1. The audited application commit is
`b02208c38c0cc945aff218da44dfb56c079e1274`, originally PR #112's head. Do not
silently switch to a different application base; refresh changed paths/findings
if the chosen execution base contains later code.

| PR | Conventional title | Audit work | Depends on | Delivery |
|---|---|---|---|---|
| 1 | `test: make discovery and frontend regression oracles reliable` | F02, F03, environment isolation | Planning base | Pending |
| 2 | `test: strengthen render cache prompt and deadline contracts` | F07, F08, F16; four bounded duplicates | 1 | Pending |
| 3 | `test: reuse successful wheel builds across packaging checks` | F01 | 2 | Pending |
| 4 | `test: coordinate worker and filesystem races with explicit gates` | F04; fake/process scheduling and ownership | 3 | Pending |
| 5 | `test: right-size stage fixtures and verify live reads and republish` | F06, F16; placeholder rule | 4 | Pending |
| 6 | `test: separate cleanup and render rules from pipeline setup` | F05, F09; market-block formatting | 5 | Pending |
| 7 | `test: seed valid proposals and model HTTP and provider contracts` | F11, F12; schema doubles and builders | 6 | Pending |
| 8 | `refactor: test calibration geometry at a focused interface` | F10; preserve F03 | 7 | Pending |
| 9 | `test: move CLI formatting and application cases to their owners` | F22; secrets/picker ownership | 8 | Pending |
| 10 | `test: control UI clocks and simplify presentation assertions` | F15, F19–F21; builders/alias cases | 9 | Pending |
| 11 | `test: separate pure frontend and prototype execution environments` | Node/DOM/design projects and aligned gates | 10 | Pending |
| 12 | `test: retain browser seams and make screenshot capture opt-in` | F13, F14; stable browser selectors | 11 | Pending |
| 13 | `test: make live provider journeys and pagination meaningful` | F17, F18; AI progress contract | 12 | Pending |
| 14 | `docs: record test refactor coverage and measured results` | Complete evidence and retained good tests | 13 | Pending |

Priority drives the sequence within a viable stack: repair misleading green
checks first, deliver the largest measured build saving early, then remove
incidental setup before extracting or deleting upper cases. PR 14 closes the
map, not unfinished implementation. An unexpectedly large PR splits into named
adjacent layers; update the table, map and briefs before starting its successor.

Aim for 5–12 changed source/test files and 250–600 changed lines per builder;
the review limit is 1,500 added/deleted lines (3,000 for PR 9's mechanical
subject relocations), measured by
`git diff --shortstat <base>...HEAD`. Report mechanical moves, regenerated
goldens and evidence separately. This is a review budget, not a code-size goal;
use `scripts/sloc.py` if assessing actual code size. Do not reduce useful
assertions or hide scope to meet it. Split a layer before freezing its tip if
its scope needs more room.

## Preflight environment block

Create `execution.md` beside this plan with the completed environment block,
baseline evidence, per-PR ledger and case replacement ledger. Record branch,
worktree, agent id, base SHA, build tip, final tip, PR number/URL and state
(`building`, `finishing`, `open`, `green`) for every layer. Paste the environment
block into every BUILD-BRIEF; each brief names this plan's exact PR section,
T requirements, seams, target subjects and exit conditions.

| Field | Required execution record |
|---|---|
| Plan/spec/UI inputs | Paths to this plan, spec, interactions, mockups and coverage map |
| Base | Committed planning SHA, base branch, application SHA and any revalidation |
| Shell/worktree | Cygwin zsh; explicitly `cd` to this worktree after a login shell (it starts in `/home/Admin`) |
| Toolchain | Successful `uv sync`; `npm install` in `src/ui` per skill preflight; resolved versions and any lockfile change explained; CI/release still use `npm ci` |
| Baseline | Full non-browser/non-e2e pytest and full Vitest on that exact base; failure nodeids, skips, counts and raw timing artifacts |
| Host/environment | OS, Python/Node, browser, ambient override presence, synthetic fixture recipe; no token values |
| GitHub | `gh auth status` and dry-run push result for a temporary intended branch ref; no PR created during planning |
| UI capture | Working app, `npx marver dev`, supported screenshot recipe and reference URLs; verify a real frame was captured |
| Real-shop serialization | Workflow/credential availability, current e2e run, orchestrator-owned one-at-a-time dispatch |

The audit measured 2,866 passes, two failures and seven skips in 565.23 seconds
for 2,875 hermetic cases. The two known failures were
`tests/core/unit/test_workspace.py::test_discover_finds_root_from_nested_cwd`
and `::test_discover_raises_when_not_found`; both passed with the ambient root
override removed. Record an ordinary-shell baseline with these identities and
a clean-environment comparison; PR 1 fixes their local isolation. Do not treat
these two as permanently acceptable failures after PR 1.

Browser had 97 passes in 189.84 seconds; Vitest had 997 passes over 75 files
with a 49.01-second first-start/last-end envelope. These are exploratory audit
runs, not preflight proof. Live e2e's 62 cases were not run. No audit coverage
or clean benchmark exists. Preflight reruns the required baseline and verifies
capture/GitHub/live prerequisites rather than claiming they have already passed.
If a required prerequisite fails, follow the skill's stop/report rule; do not
silently redefine a green finisher to mean local tests only.

## Shared gates and implementation method

| Gate | Exit evidence |
|---|---|
| G1 — Targeted builder | All touched Python/Vitest subjects and the complete Python unit layer pass; builder format/lint/typecheck commands from BUILD-BRIEF pass |
| G2 — Backend contracts | Ruff formatting/check, strict mypy and `uv run lint-imports` pass; protected imports and package interfaces remain valid |
| G3 — Full local verification | `./scripts/check.sh` passes with Python and frontend 85% branch floors unchanged; record scripts' actual selections and skips |
| G4 — Required browser | Built SPA + Chromium; `ETSY_LISTINGS_REQUIRE_EVERY_LAYER=1 uv run pytest -m browser` passes; opt-in artifacts excluded after PR 12 |
| G5 — Frontend build/ownership | Typecheck/lint/format-check/build, aggregate production coverage and, after PR 11, explicit required prototype verification pass |
| G6 — Preservation evidence | For changed runtime UI, same-fixture before/after at 1280×800 plus skill mockup/app comparison; for changed golden inputs, reviewed diffs and retained composition |
| G7 — Hosted and live finish | PR open, registered with thread, CI green on final SHA; serial e2e workflow green with URL, credentials never printed |
| G8 — Case traceability | Each changed/removed behavior has a lower oracle and any retained seam witness recorded; every PR's scope and exits individually accounted for |

Every implementation PR's finisher runs G2–G5, G7 and G8; G6 applies to
changed UI/golden inputs. Each builder runs G1 plus its section's targeted
subjects. PR 14 also checks the complete matched measurements. Regenerate the
OpenAPI and typed client only if an intentional HTTP shape change is actually
introduced; no such change is planned.

Builders use the TDD skill through the seams below. For an oracle improvement
that already passes correct production, demonstrate its failure against the
specific wrong boundary behavior identified by the audit, then restore the
correct implementation and record both outcomes. Label that as a sensitivity
demonstration, not an observed production bug. New extraction interfaces start
with a failing focused example before being implemented. Work one behavior
at a time; deletion-only work demonstrates retained coverage rather than
fabricating a new test that mirrors its removal. Do not commit mutants, xfails,
lower coverage thresholds or `pragma: no cover` workarounds.

The planned seams are Workspace discovery and ListingDocuments persistence;
application operations; Plan/Stage/Lockfile and `fully_applied`; exported render
maps and the documented pass-golden boundary; client/provider protocols and
real HTTP encoding; ProposalStore and input snapshots; public hook outputs,
component props and accessible DOM; pure geometry/formatting functions; real
browser decoded images/pointers/saved files; real child processes; built wheel
installation; and serial live provider journeys. Do not expose private worker
state to arrange a higher-level test.

## PR 1 — Reliable environment and frontend regression checks

**Scope:** T01, T03; F02/F03. Discovery tests arrange their own root override,
without globally removing deliberate env behavior. Repair settled AI refusal/
failure tests, the related DetailsTab disabled case, request listing argument,
and the repeated-scale callback oracle. Keep current runtime behavior.

**Entry points:** `test_workspace.py`, `useAiSeoMode.test.ts`,
`DetailsTab.test.tsx`, `QuadEditor.test.tsx` and existing deferred helpers.

**Exit conditions:** both discovery cases pass with an inherited conflicting
override and without one; explicit override tests still pass. AI cases observe
checking then a distinctive settled refusal/failure and reject incorrect
enabling. Two scale moves emit two index-0 changes with the concrete doubled
box; omitted callbacks/wrong target/wrong coordinates fail. Record these
sensitivity demonstrations before extraction.

**Targeted validation:** workspace/userpath unit subjects and the three
frontend subjects above, followed by G1. Keep this PR independent of timers
and geometry extraction in later layers.

## PR 2 — Discriminating render, cache, prompt and clock tests

**Scope:** T01, T10; F07/F08 and the prompt/deadline part of F16. Use a
high-frequency/impulse example with strict attenuation/nonidentity; prove
even-kernel rounding, cache reuse and source/parameter invalidation. LRU gets
three keys/two slots/touch order; edited images assert new pixels. Change
resource content between brief-reader calls; control monotonic deadlines.

Remove the four bounded fixture-count/protocol/omitted-marker duplicates in
`test_ai_models`, `test_ai_providers`, `test_etsy_market_fake` and `test_lock`.
For the byte-compatibility claim, retain the genuine omitted-marker test; if
current requirements demand exact historic bytes, replace with a literal
baseline instead. Review other DTO storage-only candidates individually and
record keep/consolidate decisions without broad model deletion.

**Exit conditions:** identity smoothing, ignored rounding, recompute/overwrite,
FIFO eviction, stale pixels and cached prompt constants fail the relevant
strengthened checks. Before/at/after cutoff and nonnegative remaining time
use no real sleep. Documented cache identity/read-only/accounting, parsed AI
counts/defaults/frozen semantics, fake FIFO/fidelity and lock merge/decode
remain. Target those eight subjects plus validation and cache concurrency.

## PR 3 — Share compatible real packaging artifacts

**Scope:** T05; F01. Refactor `tests/test_wheel_frontend.py` so freshness,
archive contents and no-Node/no-checkout installation consume a module-scoped
immutable wheel built from deliberately stale dist assets. Consumers copy
only where mutation/isolation needs it. Keep independent missing-index and
sdist-to-wheel projects; do not mock npm/Hatch out of the contract.

**Exit conditions:** the five meaningful behaviors still pass using three
wheel build attempts (plus the retained sdist build) instead of five wheel
attempts. Stale assets
are actually replaced, npm source is absent, sdist is complete, missing index
fails, and installed index/assets serve without checkout or Node. Record
matched target-file timings and artifact reuse; no promised percentage. Run
the complete packaging subject, installed-server checks and G1.

## PR 4 — Deterministic backend races and process subjects

**Scope:** T03, T08, T13; F04 and fake-process scheduling. Replace global
slow-YAML/path hooks and start-order guesses in listing/template operations,
listing-write HTTP tests and run conflict/queued-cancel/readiness tests with
bounded entry/release gates through existing host/persistence seams.

Signal fake Popen creation before completion, explicitly join all helper
workers and release in `finally`. Split real descendants/UTF-8/process-boundary
cases from `test_ai_process` into one behavior/process subject; leave fake
process orchestration units in their own subject.

**Exit conditions:** the intended lock holder has entered before its contender;
final documents prove no lost edit/invalid rename and HTTP conflict/cancellation
has a real active/queued precondition. No helper thread or held gate survives
failure. Real timeout/cancel kills descendants and real UTF-8 still passes.
No new production scheduling or concurrency is introduced. Repeat the focused
race subjects enough to exercise ordering (ten targeted runs) without claiming
that repetition proves universal absence of flakes.

**Targets:** listing/template operation races, listing-writes/run API subjects,
AI process units/new process behavior and existing AI-run gated controls.

## PR 5 — Smaller stage fixtures and honest execution claims

**Scope:** T01/T05; F06 and stage part of F16. Build matched small synthetic
profile/catalog/design fixtures for non-resolution Printify and shared
pipeline cases. Retain independent exact/tolerance/undersized dimensions and
representative full-resolution coverage; do not bypass resolution validation.

The read-before-write case changes live fake state or observes public client
reads after initial apply. The changed-price case actually republishes and
asserts its public outcome. Keep adapter-expanded variants at HTTP contracts.
Move largest-placeholder selection from an HTTP transcript into the model
unit subject, retaining real nested placeholder decoding.

**Exit conditions:** product idempotency/pricing/adoption/color disabling still
pass; resolution boundaries reject undersized inputs. Stale live reuse and a
missing second publish are detected. Smaller setup cost is measured against
the same scenarios. Targets are Printify/publish stages, product gates,
catalog models/HTTP and other consumers of the shared pipeline builder.

## PR 6 — Cleanup predicates and independent render/format inputs

**Scope:** T02/T06/T07; F05/F09 and market formatter recommendation. Add the
typed `fully_applied` table for error, absent plan, blocked work, incomplete
marker and full success. Use simple Stage implementations for actual proposal
removal/preservation; retain one full pipeline success, CLI/HTTP entry wiring
and stop-after-last-runnable-stage cleanup.

Give downstream pass goldens fixed prewarped/upstream arrays with explicit
maps; retain warp and complete composite goldens. Formatter-only market block
cases take literal `MarketResult` inputs; keep one research→block golden.

**Exit conditions:** cleanup condition matrix detects each missing guard;
orchestration physically removes only eligible proposals. A local warp defect
affects its pass golden and composition, not independently seeded downstream
cases. Field order/top eight/delimiters/restricted fields/empty market output
remain independently checked. Review golden fixture/image diffs before any
regeneration. Targets: cleanup/run subjects, pass/composite/promotion goldens,
market block, scoring/phrases/research controls.

## PR 7 — Valid seeding and honest adapter/double contracts

**Scope:** T06/T08; F11/F12. Provide a small valid proposal builder with real
`ListingAiInputs.prepare().snapshot`, deterministic facts and explicit origin.
GET/PATCH/staleness/schema/rename mappings seed ProposalStore directly and
avoid lifespan startup when worker behavior is not the subject. Retain genuine
generation, restart/replay, cancellation and lifecycle integrations.

Replace identity-based AI schema dispatch with recognized equivalent schema
content/shape and unknown-schema refusal. Add typed HTTP Responses and verify
calibrator URL/method/path/body/status/header behavior without `as never`.
The current adapter returns null for returned API errors; accurately document
and test that existing behavior with real 404 and 500 responses. If current
requirements conflict, record a separate explicit amendment before changing
product handling—this test refactor itself does not add a new error UX.

**Exit conditions:** no unrelated AI chain seeds a mapping-only case; valid
snapshot/current/stale/origin behavior is unchanged. Copied known schemas take
the same fake path and unknown schemas fail clearly. Incorrect endpoint/body/
modification-header handling fails. Targets: proposals HTTP/core operations,
durable/AI-run controls, shared AI double consumers and calibrator API tests.

## PR 8 — Focused calibration geometry

**Scope:** T02/T09; F10. Extract a cohesive pure geometry module used
by QuadEditor for move/corner scaling/anchors/clamping. Preserve public props,
event routing and gesture start state. Move coordinate matrices below DOM,
keeping focused modifier/start/end/selection/callback cases and the PR 1
nonempty repeated-move oracle at the appropriate rule plus wiring seams.

**Exit conditions:** pure geometry tests need no React/CTM/global rectangle
shim; browser non-identity drag/scale/clipping and saved geometry pass with
unchanged appearance. No protected/public export boundary is weakened. G6
compares the preflight calibrator baseline with the unchanged result. Targets:
geometry/QuadEditor and calibration browser subjects.

## PR 9 — Focused CLI formatting and subject ownership

**Scope:** T02/T13; F22. Move Plan formatting permutations to direct typed
inputs, retain one CLI plan refusal and real apply-output witness, and remove
the duplicate single ANSI swatch check. Move pure garment/pricing/creation
picker cases to their core subjects. Move Printify local credential-discovery
cases out of catalog HTTP into secrets units without losing named
credential/file guidance.

**Exit conditions:** formatter matrices use engine Plans rather than computing
diffs; one real plan/apply output witness remains. ANSI order/suffix/encoding/
suppression and actual picker terminal behavior stay covered. Application
cases appear once under their core subject with explicit fixtures. Printify
credential errors name the required credential and file. No production import
contract changes just to accommodate a test. Targets: CLI reporting/surface/
picker/new, moved core operation subjects and secrets/catalog contracts.

## PR 10 — Controlled frontend clocks and presentation checks

**Scope:** T04/T08/T10; F15/F19/F20/F21. Share typed ListingDetail and
small deferred/timestamp builders with scenario-local overrides. Replace
preview, empty-color, autosave/page and mark-seen real sleeps with controlled
timers and separately completed requests. Improve ordinary keyboard/typing
interactions when these cases are touched; retain needed low-level pointer/
media events and meaningful sequence checks.

Strengthen last-successful-save Reset, remove its unsupported cache-policy
negative, assess alias-only cases and delete only redundant presentations/dead
classes. Move exact reel positions into child tests before any parent removal;
keep one parent reel witness plus add/remove/swatches/preview derivation.
Preserve title/drawer focus and mode switching instead of wrapper assertions.

**Exit conditions:** intended debounce/exit/race outcomes happen after explicit
clock/request settlement; no late fetch, timer or mock leak. Every original
case is collected once or has an explicit deletion/replacement record. Prototype
tests remain in the existing gate until PR 11 separates their execution.
Target affected hooks/pages, ImagesTab/MediaReel/MediaLocator/DetailsTab and
shared builders, then full Vitest. Benchmark the matched timer-heavy workload.

## PR 11 — Separate frontend dependency environments

**Scope:** T13. Split Vitest using the locked version's supported project
configuration: the eleven pure subjects run in Node; DOM/hooks/storage stay
jsdom. Give four design prototype cases their own required command, included
in check.sh/CI. Keep cleanup-before-restore, production coverage scope and the
85% aggregate branch floor. Update workflow and local script together.

**Exit conditions:** every retained case is collected exactly once in its
intended project. The 172 audit-time pure cases require no DOM setup; no
module moves into Node if it requires DOM. Prototype cases still run as
required and never count as production coverage. Per-project runs and the
aggregate production coverage command work with the locked Vitest version;
no dependency upgrade is used to avoid configuration work. Targets: Node/DOM/
design projects, setup/config/scripts and CI selection; benchmark the matched
complete frontend workload before/after separation.

## PR 12 — Narrow browser responsibilities and opt-in captures

**Scope:** T02/T11; F13/F14. Remove provider-order duplication only after the
core fallback assertion and any distinct warning presentation are identified.
Keep repair-failure→Try again browser wiring; exact repair counts stay lower.
Common-copy browser expectations use literal text plus saved ref/lead, with
render/deploy setup removed because lower literal product/Etsy assertions exist.

The five artifact-only screenshot cases leave ordinary browser collection but
remain runnable through an explicit command/marker. Update marker selection,
CI, check.sh and selection tests consistently; required-browser environment
still refuses missing prerequisites. Prefer semantic locators or existing
stable hooks in changed browser helpers, preserving genuine style/geometry.

**Exit conditions:** all five named screenshots are produced by the documented
opt-in path; normal browser collection excludes them while executing real
kind/PNG/YAML/geometry/reload/autosave witnesses. No browser-only fallback UI
behavior is lost. Literal description/shared-copy regressions fail. Run the
full required browser suite, opt-in capture command and selection controls.

## PR 13 — Self-contained live journeys and real pagination

**Scope:** T12; F17/F18. Failed publish owns its unlock assertion. Replace the
nine order-dependent Phase 3 functions with a deliberate milestone journey
or a prepared-state structure where each remaining function can run selected.
Preserve every meaningful provider/draft/media/unlock milestone and cleanup;
do not create nine remote products just for isolation.

Delete the never-set SKU claim and vendor-title trivia; consolidate resolution
fetches while keeping brand/model and raw shape fidelity. Add a controlled
two-page public client contract with explicit distinct aggregated IDs; retain
a seeded nonempty live smoke only where provider verification adds value.
Inspect the AI e2e progress requirement and use ordered required milestones/
persisted result instead of duplicate incidental notifications unless the
public SSE contract explicitly requires them.

**Exit conditions:** no selected live case depends on a previous test; the
failed-publish case proves its own failure and unlocked state. Pagination
rejects ignored page/empty-result shortcuts. All Phase 3 milestones, no-write
market verification and AI persistent completion remain. Local fake/HTTP
targets pass, then the finisher alone runs the live suite serially and records
its URL. Missing/stale credentials are reported, never counted as green.

## PR 14 — Close equivalence, coverage and measurement evidence

**Scope:** T14; every F and supporting map row. This PR records delivered PR
links, replacement/deletion/retention ledger, actual dependency classes and
matched measurements. Refresh testing/contributor descriptions and docs index
to reflect new commands/projects/artifact roles; do not claim unimplemented
architecture. No substantive unfinished refactor moves into this PR by default.

**Exit conditions:** all 22 F rows and supporting recommendations have exact
implementation/retain evidence, with no unnamed deferral. Good-test protection
has named witnesses for idempotency, retry/currency/path safety, SSE/restart/
fingerprints, real process cleanup, encoding, composition and release install.
G2–G8 pass at the final SHA. Record one fresh full baseline/final comparison
and three repeated matched focused runs for packaging, stage/cleanup targets
and frontend environment changes; report median/range, cache conditions and
collection changes. No speedup or pyramid claim is based solely on fewer cases.

Verify all PRs are open/linked/green, including serial live finish URLs, and
write deviations against the plan. The final report describes measured gains,
retained assurance and any requirement-based decisions to keep a candidate.

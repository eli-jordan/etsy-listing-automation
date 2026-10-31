# Admin page implementation plan

Written 2026-10-30 from the agreed Shop and Settings mockups and planning
interview. Status: PRs 1–3 implemented on stacked branches; Settings and AI
configuration remain later deliveries.
The remaining mockup states were approved on 2026-10-30 and are recorded in
the [interaction companion](interactions.md), with prototype source references
and screenshots. There is deliberately no separate `spec.md`.
The settled requirements below and the interaction companion are
the implementation inputs, by the seller's explicit choice.

The clickable source is
[`src/ui/design/scenes/admin-shop/`](../../../src/ui/design/scenes/admin-shop/),
on the `admin-shop` board. The Settings layout comes from direction B of
`admin-settings`; Shop uses the revised direction A. Keep these fixture-driven
prototypes when building the real page. Copy suitable markup and styles into
production components without wiring the frames to APIs.

## Settled requirements

Replace the sidebar's Setup placeholder with Admin at `/admin`. Its local
navigation has Shop and Settings, with Connected shops and Listing defaults
under Shop. Selection is page state, not a URL parameter.

Fields save on blur; toggles, sliders and drags save when the action finishes.
The server validates the complete candidate document with the owning pydantic
model. Invalid input remains visible with a field error and never reaches disk.
Shop and settings reads return separate hashes of their exact file contents.
Every save compares its expected hash under the same lock as read, validation
and atomic replace. A conflict asks the seller to reload; it never overwrites
an external edit. Adopt the returned hash after a successful write and serialize
the page's saves to avoid conflicts with its own writes.

Every YAML writer must preserve comments, key order and untouched source bytes,
including whitespace and line endings. A semantic no-op leaves the whole file
byte-identical and does not replace it. Use ruamel round-trip documents through
the existing workspace owners, with source-preserving editing where dumping
alone changes unrelated bytes. See [ADR-0055](../../adr/0055-preserve-yaml-source-when-editing.md).

### Shop

Connected shops are read-only. Show the configured Etsy and Printify names and
ids. A missing connection has a "Not connected" row and the appropriate
`etsy-listings setup` or `etsy-listings auth etsy|printify` command. Distinguish
a missing configuration from a lookup failure, retaining configured identity
when a service cannot be reached. Do not show credentials or shop-switch controls.

Currency is the only danger-zone action. Offer Etsy's supported currencies and
require the warning modal's acknowledgement before saving. Explain that this
changes the workspace currency without converting prices or changing existing
remote listings. Preserve ADR-0006 and ADR-0019's explicit currency and minor-unit
rules; do not rewrite listing prices or lockfiles. A saved price with the old
explicit currency remains unchanged and may require a seller edit before the
next deployment validates. The prototype uses
[Etsy's supported list](https://help.etsy.com/hc/en-us/articles/360000337767-Currencies-Supported-for-Etsy-Payments),
checked 2026-10-30; verify it again during implementation.

The PR 3 review narrowed the picker and PATCH boundary to currencies with ISO
4217 minor-unit exponent 2. Etsy lists 22 currencies; 21 are offered. VND is
excluded because ADR-0019's current `Money.minor_units` assumes two decimals.
Its arithmetic and the broader Defaults model are unchanged.

Derive Print on demand from `who_made: someone_else`,
`when_made: made_to_order` and `is_supply: false`. There is no stored preset key.
Selecting it writes those values together and displays their read-only summary.
Custom displays their individual selectors directly. Selecting Custom alone
does not change values, so matching values display as Print on demand on reload.
Production partner remains independently editable under Fulfilment and policies.

Fulfilment and policies also contains preferred print provider, shipping
profile, return policy and renewal. Keep the existing configuration identities:
names for providers, profiles and partners; structured terms for return policy.
Use live Etsy lookups for shop-owned lists and Printify's full provider catalog,
with the current preference first. A preferred provider only preselects `new`
when it offers the selected garment. Refresh lists on window focus and provide
manual retry. Retain the saved selection when lookup fails or omits it.
Etsy lists must not acquire a disk TTL cache, per ADR-0033.

Create links open Etsy's shipping profiles, return policies and production
partners in a new tab. Preferred print provider links to browsing Printify's
catalog; the seller cannot create a Printify provider. Refreshing the list never
selects a newly found item automatically. Every field has an explanatory info card.

### Settings

Batch AI is a whole-number slider from 1 to 8, default 1. The next dispatch
reads the new value; already running drafts finish. Editor runs do not consume
the batch limit, per ADR-0048.

Market weights use draggable dividers with keyboard equivalents. Display whole
percentages totaling 100 and save those integers after a completed edit.
Existing relative weights still load and normalize for display without an
automatic write. Keep validation for unknown metrics, negatives and an all-zero
total. Reset restores the model's defaults, currently 30/30/20/10/5/5 for
reviews, favourites per day, search rank, views per day, shop sales and shop rating.

AI uses one ordered `ai.providers` list. A row's number, or dash when off,
toggles it; its handle reorders it. At least one provider must remain enabled.
Omitted providers are off. No `ai` block means Codex, Claude and Grok enabled
in that order, with account-default model and effort. A provider omitted from
the file still appears as an off row that can be enabled in the UI.

Each provider has one model and effort for all tasks. Account default omits
the corresponding CLI flag. Codex lists come from `codex debug models`, including
per-model effort choices, excluding `ultra` and any service-tier control.
Claude uses a curated list of pinned ids, excluding fable, with low, medium,
high, xhigh and max effort. Grok models come from `grok models`, with low,
medium and high effort. Verify the installed CLIs' discovery format and flags
in the implementation PR. Attempt discovery at startup, cache for 30 minutes
and refresh on expiry or explicit Refresh. Discovery failure retains saved
values and Account default. Keep saved, no-longer-offered values with a warning
and still pass them to the CLI; a rejected model or effort allows fallback.
See [ADR-0056](../../adr/0056-configure-ai-providers-per-workspace.md).

Time limits apply to every AI run, including editor AI Mode, standalone brief
drafting, market-query extraction and batch brief runs. `ai.step_limit_minutes`
is an integer from 1 to 15, default 5. `ai.run_limit_minutes` is an integer from
5 to 60, default 20, and must be at least enabled providers times the step
limit. Raising the step limit or enabling a provider raises the run limit if
needed, in the same save. Lowering either does not lower the run limit for the
seller. Clamp the run slider's minimum to the computed floor.

A provider attempt and its one repair share the step budget. Fallback gets a
fresh step budget, bounded by the remaining run time. The whole-run deadline
also covers research and successive tasks; the provider-count floor is a
configuration rule, not a promise that all tasks can exhaust every allowance.
Snapshot provider settings and limits at run start. Running jobs keep their
snapshot. See [ADR-0057](../../adr/0057-bound-ai-attempts-and-runs.md).

Unknown keys or providers, duplicate providers, an empty enabled chain and
invalid limit relationships refuse to load, naming the file and dotted key.
Never silently repair a hand-edited file or fall back to defaults after a
validation failure. Missing files, sections and optional keys keep defaults.

```yaml
market_seo:
  weights:
    reviews: 30
    favourites_per_day: 35
    search_rank: 20
    views_per_day: 10
    shop_sales: 5
    shop_rating: 0
batch_ai:
  concurrency: 2
ai:
  providers:
    - name: claude
      enabled: true
      model: claude-opus-5-5
      effort: high
    - name: codex
      enabled: true
      model: gpt-6.1-sol
      effort: medium
    - name: grok
      enabled: false
      model: grok-4.4
  step_limit_minutes: 5
  run_limit_minutes: 20
```

Model ids here are illustrative saved values, not a current provider catalog.
Omitted model and effort mean Account default. The minimal explicit provider
list `[{name: claude}, {name: codex}]` enables those two in that order.

## Delivery sequence

Commit the plan and ADRs as documentation before implementation. Record the
resulting stack-base commit and each delivery PR link here when execution starts.
The six PRs stack in this order, each based on the preceding tip. The interaction
companion and reviewed mockups are now present. The seller explicitly
waived the implement-stack skill's separate product-spec requirement; do not
create a redundant spec to satisfy that template.

Execution started on 2026-10-30 from stack-base commit `5bbcd7df`.

| PR | Branch | Link |
|---|---|---|
| 1 | `feat/admin-1-local-fixes` | To be recorded |
| 3 | `feat/admin-3-shop` | [PR #146](https://github.com/eli-jordan/etsy-listing-automation/pull/146) |
| 4 | `feat/admin-4-settings` | [PR #147](https://github.com/eli-jordan/etsy-listing-automation/pull/147) |

### PR 1: carry the local timeout and catalog fixes

Bring in both changes from the main checkout as one PR. The 2026-10-30 inventory
has 15 modified files, 148 insertions and 27 deletions. Re-read its diff when
executing; do not copy unrelated work that appears later or alter that checkout.
Include the AI models, errors, providers, orchestrator and runner documentation,
their tests, Printify `resolve.py`, catalog/product-stage tests, architecture,
AI interactions, market spec and getting-started updates.

The local change raises the shared task deadline from 60 to 300 seconds and the
run watchdog from 180 to 1,200 seconds. It does not yet implement a fresh budget
for each fallback provider. Catalog matching adds the explicit Comfort Colors
brand alias and bounded closest-name suggestions, preserving refusal of unknown
or ambiguous matches. Similarity suggests names; it never chooses a blueprint.

Exit when the complete inventoried diff is included, the existing added
orchestrator, runner, catalog and product-stage tests pass, and the shared gates
pass. Record the source diff or commit so this uncommitted work cannot be lost
or mistaken for a dependency already on main.

Source: the main checkout's uncommitted `git diff --binary` captured on
2026-10-30 (sha256 `afd2c98efa12743fc231d1cb62383ddaf94fddd691354591873ad262d47e05e1`;
15 files, +148/-27), plus local-only commit `e970d3ef` amending ADR-0005.
Both are carried unchanged.

### PR 2: preserve every YAML document during edits

Add the round-trip dependency and shared document editing support under
`core/workspace`. Convert existing writers in `listing_documents.py`,
`workspace.py`, `atomic.py`, `calibration.py`, `application/workspace_setup.py`,
`garment_profiles.py` and `pricing_plans.py`, including their transitive users
for listing templates and batch creation. Inventory dump/write sites again
before declaring the conversion complete. Reads can retain their existing
validated models; they must not discard the source document used for writing.

Keep ListingDocuments as the sole listing reader/writer and lock owner. Preserve
calibration transaction recovery and existing create-if-absent behaviour. New
files use documented defaults; existing files change only the edited values.
Update setup's claim that comments are discarded.

Exit when golden text fixtures prove byte-identical no-ops and untouched spans
for comments, ordering, quotes, block scalars, Unicode, CRLF/LF, flow collections
and nested edits. Exercise actual writer owners, not just the helper. Existing
calibration recovery and listing-lock tests and all shared gates pass.

### PR 3: add `/admin` and the Shop tab

Add the route and Admin sidebar item with the selected sidebar layout. Put
reusable read/edit operations in `core/application`, document their interfaces
in its initializer, and keep layout, file revision and atomic writing in
`core/workspace`. Build thin FastAPI routes and regenerate OpenAPI and the typed
client. Use the existing connection factories and Etsy lookup protocols.

Implement Shop reads and patches, revision conflicts, read-only connected and
disconnected rows, supported-currency warning modal, derived POD/Custom controls,
Fulfilment and policies, info cards, external Create links and focus refresh.
Extend the Printify catalog protocol, real client and fake with a full-provider
list; it currently only lists providers for a blueprint. Preserve existing
Etsy reference resolution at deploy time.

Exit when fake-backed operation/API tests prove validation, atomic conflicts,
no-op writes and lookup failure retention, and Vitest/browser tests cover the
modal acknowledgement/cancel, connection rows, tier changes, defaults, Create
round trip and retry. Confirm a defaults edit does not rewrite existing listing
files or remote state. Shared gates pass. Settings may remain visibly unavailable
until PR 4; do not ship live-looking controls that do nothing.

### PR 4: add Settings, batch concurrency and market weights

Add settings reads and atomic patches with their own file revision, using PR 3's
save pattern. Enforce concurrency's upper bound in config. Build the 1–8 slider,
draggable and keyboard-operable market dividers, percentages and Reset. Normalize
relative weights only for display until the seller edits them. Keep zero-weight
metrics reachable and the sum exactly 100.

Exit when tests cover missing-file defaults, bad-key refusal, invalid patches,
conflicts, rapid serialized saves, percentage normalization, reset and divider
keyboard/pointer actions. Queue tests prove the next dispatch uses the new limit
and lowering it leaves active runs alone. Shared gates pass.

### PR 5: configure AI providers, models and effort

The local BUILD implementation records verified installed formats and flags
in [Provider CLI contracts](provider-cli-contracts.md). PR6 owns configurable
limits and fresh fallback budgets; PR5 keeps the inherited fixed defaults.

Add the ordered list model and wire it into the existing ProviderFactory for
readiness and every AI caller. Pass model/effort flags in each adapter while
preserving read-only tools, cancellation and process-tree cleanup. Build the
number/dash toggle, reorder handle with keyboard support, per-provider selectors,
stale-value warning, discovery status and Refresh. Keep the old fixed time
defaults until PR 6.

Exit when tests cover ordering, omitted/disabled providers, at-least-one refusal,
duplicates/unknown names, exact argv and flag omission, rejected stale-value
fallback, discovery failure, expiry and explicit refresh. Runs use a captured
configuration; subsequent runs see changes. Amend the AI SEO plan's fixed-chain
and account-model decisions and adapter comments to cite ADR-0056. Shared gates pass.

### PR 6: configure AI step and run time limits

The time-limit mockups were approved on 2026-10-30. Add both validated
keys, their controls, dynamic floor and the coupled save when a provider is enabled
or the step limit rises. Replace the fixed task/run constants with the run's
captured limits and implement ADR-0057's attempt budgets. Render timeout messages
from the actual configured limit. Update affected AI and market requirements,
architecture and operator guidance together.

Exit when clock-controlled tests prove defaults, both range boundaries, file-load
refusals, fresh fallback budgets, repair sharing, run deadline clipping and
process-tree termination. UI tests prove the floor, automatic increases and
next-run behaviour. Cover every AI entry point with fakes and preserve brief-only
batch semantics. Shared gates pass.

## Shared gates

| Gate | Exit condition |
|---|---|
| G1 | Test-first for production behaviour. Fakes test workflows, cassette/subprocess contracts test vendor payloads and CLI arguments. No new real-shop e2e cases. |
| G2 | Run `./scripts/check.sh` from the repository root in Cygwin zsh. Python and frontend retain their 85% branch floors. Do not lower gates or exclude new code to pass. |
| G3 | Run `npm run test:design` separately from `src/ui`. For UI PRs, build the SPA and run the relevant `pytest -m browser` cases. Frames stay fixture-driven. |
| G4 | Regenerate `docs/openapi.json` and the typed client after API shape changes. Keep core free of server/CLI imports and pass Import Linter. |
| G5 | Compare UI behaviour with the reviewed mockups and interaction companion. Validate keyboard controls, focus, save/error/conflict states and both themes. |
| G6 | Local e2e waived by the seller on 2026-10-30; the try-workspace was removed. Run the existing GitHub e2e workflow serially after green CI and record its URL. Never use the seller's real local workspace. |
| G7 | Update affected current requirements, architecture, guides and ADR citations in the owning PR. Record its URL and any agreed deviation here. |

## Approved design reference

The clickable prototype now includes time-limit controls and their automatic
increase state, model-list Refresh and failure state, disconnected shops, failed
lookups, and invalid/conflicting saves. These additions were approved on
2026-10-30 and are covered by [the interaction document](interactions.md).
Start with `settings-limits/d-revised` and
`settings-raised/d-revised` on the `admin-shop` board. The prior prototype is
preserved as `admin-shop-v1` on the archive board. Screenshots are checked in
beside the interaction document; the prototype stays fixture-driven during
implementation. The Shop implementation preserves these fixture-driven frames.

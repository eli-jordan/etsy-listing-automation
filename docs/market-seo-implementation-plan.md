# Market-informed SEO implementation plan

**Status:** proposed implementation plan.

It implements:

- [Market-informed SEO](market-seo.md), the product spec;
- [Market-informed SEO interactions](ui-market-seo-interactions.md), the UI
  companion; and
- the Marver mockups that document references (the **Market-informed SEO**
  board, `src/etsy_listings/ui/frontend/design/scenes/market-seo/`).

Like the spec, this plan is not an authority over [prd.md](prd.md).

## Settled decisions

These come from the planning interview. They are recorded in PRD 71 (with
amendments to PRD 4, 13 and 68), [market-seo.md](market-seo.md) and the two
interactions docs. This table is a summary; those documents are the authority.

| Topic | Decision |
|---|---|
| Progress transport | An **AI run**, following the plan/apply runs pattern: an in-memory registry, `POST` to create, SSE events with `Last-Event-ID` replay, `GET ?listing=` to reattach, `DELETE` to cancel. It has **its own registry and its own thread per run**, never the plan/apply worker thread. |
| Run scope | One run covers the brief (only when `draft_brief` is true), then query extraction and market search, then the proposal. It needs a saved listing that has a design and a garment profile. |
| Concurrency | One active AI run per listing. A second `POST` gets 409 naming the active run. A finished run is kept until the next run for that listing replaces it. Nothing survives a restart. |
| Leaving and cancelling | Leaving the editor or reloading does not cancel. The editor reattaches and the events replay. **Cancel** sends `DELETE`, which sets the run's cancel event and so kills the provider subprocess tree. A brief or snapshot already written stays. |
| Brief write | The **server** writes the drafted brief into `listing.yaml`, only if the saved brief is still empty. It does this under a new per-listing write lock that PATCH autosave and rename also take. Then it emits `brief {text, written}`. The editor puts the text into the field without autosaving it again. |
| Auto chain (PRD 68) | Picking a design while the brief is empty arms the chain in the editor. It fires once, the first time a successful save has a name, design and garment profile. It sends `draft_brief = (brief still empty)`. Picking another design re-arms it; leaving or reloading disarms it. |
| AI Mode button | Starts a run with `draft_brief` set when the brief is empty, so a failed automatic draft can be started again from the button. A brief that already has text is sent with `draft_brief=false`, and the Brief node shows as **skipped**. |
| Deadlines | Each provider call (brief, extraction, proposal) keeps the orchestrator's 60s. Market search has no limit of its own. The whole run is capped at **3 minutes**. |
| Old endpoints | `POST /api/ai/design-brief` and `POST /api/listings/{name}/ai-seo/proposal` are retired, with their clients and tests. `GET …/ai-seo/readiness` stays. |
| Suggestions | `aiSeoStorage` (localStorage, 1 day) stays the lasting home. The browser stores the `proposal` event there. Replay only covers a run that is in flight or has just finished. |
| Taxonomy | No taxonomy filter. `market-queries.md` receives the garment's display title, and each query must end in the buyer's word for the item type. Validation still only checks for three unique, non-empty queries. |
| Rate limits | No stored budgets. Reuse `Transport`'s retry policy. At most 5 Etsy calls in flight. Wait for the next second when `x-remaining-this-second` is 0. Log `x-remaining-today` at debug level. |
| Snapshot lifecycle | `.cache/market/snapshots/{name}.json`. It moves with the listing on rename and is removed on delete. A failed run doesn't replace it. |
| Panel data | Batch call `includes=Shop,Images`: the thumbnail is the first image's 170px URL. "Your shop" means `shop_id` equals `shop.yaml`'s `etsy.shop_id`. The score is shown as `round(weighted percentile sum ÷ total weight × 100)`. |
| Phrase ticks | A phrase is ticked when it matches a suggested tag, or appears in a suggested title or lead (case-insensitive). Computed in the browser. |
| UI | Indicator as mocked; fades 4s after *Suggestions ready*; warning and failed states stay. No panel before the first snapshot. The panel shows loading as soon as market research starts. Below 1100px it stacks under the fields. The Listings/Phrases switch reuses `.seg`. Phosphor becomes a runtime dependency. |
| Testing | Unit, API and Vitest tests with fakes. One live e2e test for market search. One full-run e2e test whose AI provider is chosen by `E2E_REAL_AI=1` (real CLIs, locally) and defaults to fakes (CI). |

## Run contract

Every PR from PR 5 on builds against this contract. PR 5 owns it and publishes
it in `docs/openapi.json`.

```
POST   /api/ai/runs                 {listing, draft_brief} -> 202 AiRunSummary | 409 {active_run} | 409 {reason}
GET    /api/ai/runs?listing=        the listing's current or most recent run, or 404
GET    /api/ai/runs/{id}            AiRunDetail: phase, steps, events so far
GET    /api/ai/runs/{id}/events     text/event-stream; replays after Last-Event-ID
DELETE /api/ai/runs/{id}            cancel; 409 if already terminal
GET    /api/listings/{name}/market  MarketSnapshot | 404 when there is none   (PR 8)
```

`POST` refuses with 409 `{reason}` using the same readiness rules as today,
except the brief rule: an empty brief is allowed when `draft_brief` is true. A
missing garment profile is also refused.

Events are Pydantic models serialised as `event: <type>` / `data: <json>`,
each with an `id`:

| Event | Payload | Emitted |
|---|---|---|
| `step` | `{id: "brief"\|"market"\|"seo", state: "pending"\|"active"\|"done"\|"skipped"\|"warning"\|"failed", detail?: str}` | on every node change; the first three events set the initial states |
| `brief` | `{text, written: bool}` | after the brief is drafted. `written` is false if the seller filled the field in the meantime |
| `queries` | `{queries: [str, str, str]}` | after extraction, so the panel can show *Searching Etsy for…* |
| `market` | `{snapshot: MarketSnapshot}` | after a successful or empty search, once the snapshot is written |
| `proposal` | `SeoProposalResponse`, unchanged | after validation |
| `phase` | `{phase: "done"\|"failed"\|"cancelled", message?: str}` | terminal, always last |

The indicator is a pure function of the latest `step` event for each node, so
replay rebuilds it exactly. Market failures use the spec's message, *Etsy market
search failed: \<reason\>*.

## Standard success gates

Every PR must meet all of these before it is done. Each PR below lists which
ones apply and adds its own conditions.

- **G1. Local checks green.** `scripts/check.sh` passes: ruff format and
  check, mypy, and pytest with branch coverage. In
  `src/etsy_listings/ui/frontend`, all of these pass: `npm run format:check`,
  `npm run lint`, `npm run typecheck`, `npm run test:coverage`. If browser
  tests changed, `uv run pytest -m browser` passes too.
- **G2. Coverage gates met.** Python branch coverage stays at or above the
  `fail_under = 85` in `pyproject.toml`. Vitest branch coverage stays at or
  above the 85% threshold in `vitest.config.ts`. New modules are held to the
  same floor on their own, so they don't lean on the rest of the codebase.
- **G3. PR open with green checks.** A PR is open against the previous PR in
  the stack (or `main` for PR 1), and every CI check is green: python on
  every OS in the matrix, frontend, and browser.
- **G4. e2e green on GitHub Actions.**
  1. `uv run pytest -m e2e` passes locally first.
  2. Then `gh workflow run e2e --ref <branch>` is dispatched, and the run
     (`gh run watch`) finishes green.
  3. The run URL is linked in the PR description.

  This applies to every PR, including those that don't touch e2e tests, so a
  regression in the real-shop layer is caught on the branch that caused it.
- **G5. UI compared with the mockups** (PRs with UI).
  1. Run the app and `npx marver dev` side by side at 1280×800.
  2. Take screenshots of the implemented state for each mockup frame the PR
     covers.
  3. Check them against the frame and against the interactions doc's
     sections: layout, spacing, type, colour, icons, every state, hover,
     focus, motion, and `prefers-reduced-motion`.
  4. Fix every difference, or record it in the PR description as an agreed
     deviation with a reason.
  5. Attach the before/after screenshots to the PR.
- **G6. API compared with the spec** (PRs with API or client code).
  1. Go through [market-seo.md](market-seo.md), the PRD (#4, #13, #68, #71),
     and the [Run contract](#run-contract) section by section.
  2. Check each rule: parameters, filters, scoring, caching, retries,
     failures, messages and payload shapes.
  3. Every rule must be implemented and tested, or listed in the PR
     description as a deliberate deviation.
  4. If the HTTP surface changed, regenerate `docs/openapi.json` and
     `src/api/schema.ts` (`npm run gen:api`) in the same PR.
- **G7. Size.** No more than **3,000 changed lines** (`git diff --stat`
  against the parent branch, including tests; lock files and generated
  `schema.ts` / `openapi.json` don't count). A PR heading over the limit is
  split before review, not after.

## Implementation PR sequence

The PRs are stacked: each branches from the one before it. The estimates
include tests.

```
PR 1  etsy market client ──► PR 2  research pipeline ──► PR 3  caches + snapshot + settings
                                                             │
PR 4  prompts + extraction ◄─────────────────────────────────┘
  │
  ▼
PR 5  AI runs backend ──► PR 6  frontend runs + auto chain ──► PR 7  workflow indicator
                                                                  │
                          PR 9  e2e ◄── PR 8  top listings panel ◄┘
```

---

### PR 1 — `feat(etsy): read-only market search client`

**About 1,100 lines.** It adds the Etsy calls the research needs, and the
header pacing, with nothing yet using them.

**Scope**

- `clients/etsy/market.py`:
  - An `EtsyMarketClient` protocol and an `HttpEtsyMarketClient`.
  - `search_active(query, *, limit=25)` calls `findAllListingsActive` with
    `keywords`, `sort_on=score` and `buyer_country=US`, and no
    `taxonomy_id`.
  - `listings_by_ids(ids)` calls `getListingsByListingIds` with
    `includes=Shop,Images`, in chunks of 100.
  - `review_count(listing_id)` calls `getReviewsByListing` with `limit=1`
    and reads `count`.
- `clients/etsy/models.py`:
  - A `MarketCandidate` model: `listing_id`, `shop_id`, `title`, `tags`,
    `description`, `num_favorers`, `views`, `original_creation_timestamp`,
    `url`.
  - A `ShopStats` model: `shop_name`, `transaction_sold_count`,
    `review_average`, `review_count`.
  - A thumbnail URL, taken from `url_170x135` on the first image.
  - Decoding of Etsy's response shapes, including listings with missing
    optional fields.
- `clients/etsy/transport.py`, rate limiting:
  - After each response, read `x-remaining-this-second`. When it is 0, the
    next request waits until the next second. This uses the injected `sleep`
    and a shared, thread-safe gate, so the 5 concurrent market calls respect
    it.
  - Log `x-limit-per-day` and `x-remaining-today` at debug level.
  - Retries are unchanged: `DEFAULT_POLICY` with `Retry-After`.
- `clients/etsy/fakes.py`: a `FakeEtsyMarketClient` seeded with candidates,
  shops, images and review counts per query. It records calls and can inject
  429, 5xx and network errors.
- `connections.py`: build the market client from the workspace's existing
  Etsy app key and token.

**Tests**

- Unit tests for request parameters, chunking, decoding and missing fields.
- Pacing when the remaining count is 0, using the injected clock and
  `sleep`.
- Retry classification against `httpx.MockTransport`.
- The fake's behaviour.

**Success conditions**

- G1, G2, G3, G4, G6 and G7.
- No caller in `engine/`, `ui/` or the CLI uses the new client yet: it has no
  behaviour change of its own.
- Pacing is shown to hold across 5 threads, with no busy-waiting (a test with
  an injected clock).
- G6 covers the spec's *Search* and *Stats* sections and the *Quota* section
  as amended (no stored budget anywhere).

---

### PR 2 — `feat(market): filter, score and rank comparable listings`

**About 1,700 lines.** It turns three queries into 20 scored listings, a
phrase list and a market-data block, all in memory.

**Scope**

- A new `etsy_listings/market/` package, with nothing under `ui/`:
  - `models.py`: `ScoredListing` (all panel fields plus `score_raw`, `score`
    from 0 to 100, `rank`, `own_shop`, `thumbnail_url`), `PhraseScore`
    (`phrase`, `listings`, `score` from 0 to 1), `MarketResult` (queries,
    found, scored, listings, phrases, `relaxed`, `empty`), and
    `MarketWeights` with the spec's defaults.
  - `research.py`: `research(queries, client, *, today, weights, own_shop_id,
    cancel_event) -> MarketResult`.
    - Run the 3 searches with at most 5 calls in flight. Deduplicate,
      keeping each listing's best rank.
    - Filter to listings at least 30 days old. If none are left, search
      again without the age filter. If that is still empty, return an empty
      result.
    - Make one batch call for stats. Rank preliminarily on the free signals,
      with the weights rescaled to exclude reviews.
    - Fetch review counts for the top 20 only. Compute the final score.
    - Check `cancel_event` between calls.
  - `scoring.py`: the 0–1 percentile within the set, with ties sharing the
    average percentile. Shops with no review average count as lowest. Rank
    is inverted (1st is best). Also rescaling and the 0–100 display score.
  - `phrases.py`: the ranked phrase list. For each tag: how many listings use
    it, the sum of their scores, normalised to 0–1. Top 40.
  - `block.py`: the delimited market-data block (the phrase list, then the
    top 8 listings verbatim: title, tags and lead). The lead is the first
    sentence of the description. Other sellers' text goes in marked as data.

**Tests**

- Table-driven tests for:
  - percentile ties and rescaling;
  - the age filter and relaxing;
  - taking the best rank when merging duplicates;
  - top-20 rationing: exactly 20 review calls, made only for the top 20;
  - phrase normalisation and ordering;
  - block assembly, compared against a golden file in `tests/golden/`;
  - cancellation between calls.
- All against `FakeEtsyMarketClient`.

**Success conditions**

- G1, G2, G3, G4, G6 and G7.
- With an empty cache, a full research makes at most 3 + 1 + 20 calls
  (asserted through the fake's call log). A relaxed search adds at most 3
  more.
- G6 walks *Market search*, *Scoring* and *What the proposal sees* line by
  line. The golden block matches the spec's two-part structure.

---

### PR 3 — `feat(market): caches, snapshot store and settings.yaml`

**About 1,300 lines.** It makes research cheap to repeat and its result survive
a reload.

**Scope**

- `workspace/layout.py` and `workspace/workspace.py`:
  - Add the `SETTINGS_FILE = "settings.yaml"` loader. If the file or a key is
    missing, the defaults from `MarketWeights` apply. Validation errors name
    the file and key.
  - Add path helpers for `.cache/market/{search,stats,snapshots}/`.
- `market/cache.py`:
  - A 7-day TTL cache for search responses, keyed by the query plus the
    search parameters.
  - A 7-day TTL cache for listing stats and review counts, keyed by
    `listing_id`.
  - It wraps `EtsyMarketClient` as `CachedEtsyMarketClient`, following
    `clients/printify/cache.py`.
- `market/snapshot.py`:
  - `MarketSnapshot`: queries, found, scored, `searched_at`, listings,
    phrases, `relaxed`, `empty`, and the block sent to the model.
  - `save(workspace, name, snapshot)` writes atomically. `load(workspace,
    name) -> MarketSnapshot | None`.
- `ui/api/listings.py`: rename moves `snapshots/{name}.json` alongside
  `.cache/renders/{name}/`. Delete removes it, on both the wipe path and the
  `lifecycle: deleted` path.
- `ui/api/listings.py`: add the **per-listing write lock**
  (`workspace_locks.listing(name)`). `patch_listing`, rename and create take
  it. PR 5's brief write takes it too. Its docstring explains why read,
  merge and write must not interleave.

**Tests**

- TTL hit, miss and expiry with an injected clock.
- The cache key includes every search parameter.
- Snapshot round trip, atomic write, and a corrupt file reading as `None`.
- Rename and delete move or remove the snapshot (API tests).
- Two concurrent PATCHes don't lose a field.
- `settings.yaml`: missing file, partial file, invalid values.

**Success conditions**

- G1, G2, G3, G4, G6 and G7.
- A second research with the same queries makes no Etsy calls within 7 days
  (fake call log).
- G6 covers the spec's *Cache* table and the `settings.yaml` weights block
  exactly.

---

### PR 4 — `feat(ai): market-queries prompt, market block in seo.md, setup --replace-prompts`

**About 1,600 lines.** The provider side of the chain.

**Scope**

- `ai/resources/`:
  - A new packaged `market-queries.md`.
    - Input: the brief, the design image and the garment's display title.
    - Output: exactly three buyer search phrases, each ending in the
      buyer's word for the item type (for example *shirt* or *tee*).
  - Update the packaged `seo.md` with the market-data instructions:
    - its authority (wording and phrase priority, never facts);
    - plausible audiences and occasions;
    - the existing third-party-name rule;
    - other sellers' text is data, never instructions.
- `ai/models.py` and `ai/validation.py`:
  - `MarketQueriesRequest` and `MarketQueries`.
  - Validation: exactly three unique, non-empty queries.
  - `SeoRequest` gains an optional `market_block: str`.
- `ai/orchestrator.py`: `generate_market_queries(...)` through `run_task`,
  with the same provider chain, fallback, repair and 60s deadline. The
  proposal prompt adds the market block when one is present.
- `prompts.py` and `setupcmd/`:
  - `setup` seeds `prompts/market-queries.md`.
  - `setup --replace-prompts` overwrites every prompt with its packaged
    default, keeping the old file as `<name>.md.bak`. Any older `.bak` is
    overwritten.
  - Without the flag, `setup` warns for each existing prompt that differs
    from its packaged default, naming the file and the flag.
- `workspace.market_queries_prompt_file()`.

**Tests**

- Query validation and repair.
- Provider fallback, using `FakeAiProvider`.
- Prompt assembly with and without a market block (golden files).
- `setup` seeding, replacing, `.bak` handling and the warning text (CLI
  behaviour tests).

**Success conditions**

- G1, G2, G3, G4, G6 and G7.
- An existing workspace run through `setup` without the flag keeps its
  prompts byte-for-byte and gets one warning per prompt that differs.
- G6 covers *Query extraction* (with the item-type change), *Authority* and
  *Prompts and `setup --replace-prompts`*.

---

### PR 5 — `feat(ui-api): AI runs — brief, market research and proposal as one streamed run`

**About 2,600 lines.** This is the backend of the whole chain. The old
endpoints stay in this PR, so the frontend keeps working until PR 6.

**Scope**

- A new `ui/airuns/` package, mirroring `ui/runs/`:
  - `registry.py`: `AiRun` and `AiRunRegistry`, in memory. It holds one
    active run per listing and keeps the latest run for each listing until
    the next one replaces it. Each run has an event buffer with a condition
    variable, which the SSE bridge waits on.
  - `events.py`: the event models from the [Run contract](#run-contract),
    plus `AiRunSummary` and `AiRunDetail`.
  - `runner.py`: one daemon thread per run executes the chain.
    1. **Brief**, if `draft_brief` is set:
       - Call `generate_brief`.
       - Under the listing write lock, re-read the listing. Write `brief`
         only if the saved brief is still empty.
       - Emit `brief {text, written}`.
       - If `draft_brief` is not set, emit `step brief skipped`.
    2. **Market:**
       - Call `generate_market_queries` and emit `queries`.
       - Run `research` through the cached client.
       - Save the snapshot and emit `market`.
       - For an empty result, emit `step market warning` with the spec's
         *No comparable listings* detail.
    3. **SEO:** call `generate_proposal` with the market block and emit
       `proposal`.
    4. **End:** emit a terminal `phase` event.
  - A failure in extraction or search fails the run. The SEO step is left
    `pending` with the detail *Not started*, and a failed run never writes a
    snapshot.
  - Cancellation: a shared `cancel_event` is passed to every provider call
    and to `research`. A 3-minute watchdog sets it and ends the run as
    `failed`, with a timeout message.
- `ui/api/airuns.py`: the five run endpoints from the contract. `POST`
  re-checks readiness on the server, using the brief rule from the contract,
  and requires a garment profile.
  - The SSE bridge copies `ui/api/runs.py`: the same `run_in_executor` wait
    with a bounded timeout, and the same `Last-Event-ID` replay.
- `ui/api/app.py`: wire up the registry. `seo_provider_factory` and a new
  `market_client_factory` are the injection seams for tests. On shutdown,
  cancel active runs.
- `docs/openapi.json` is regenerated.

**Tests**

- Registry: claiming a listing, replacing a finished run, a 409 naming the
  active run.
- Runner, with fakes for the provider and the market client, covering every
  step-state sequence in the interactions doc's *Scenarios* table: auto
  chain, brief skipped, no comparables, market failed, brief failed.
- Brief write:
  - the field was empty, so it is written;
  - the field was filled mid-draft, so it is not written, and `written` is
    false;
  - a PATCH racing the write holds the lock.
- Cancelling at each step:
  - the subprocess cancel is observed;
  - the brief and snapshot already written stay;
  - no `proposal` event is emitted.
- The 3-minute watchdog, with an injected clock.
- SSE replay after `Last-Event-ID`.
- Reattaching with `GET ?listing=`.
- `DELETE` on a terminal run returns 409.

**Success conditions**

- G1, G2, G3, G4, G6 and G7.
- An AI run never uses the plan/apply `RunExecutor` thread. A test shows a
  plan run and an AI run making progress at the same time.
- Closing the SSE connection does not cancel the run. `DELETE` does.
- The only workspace-file write in the package is the guarded `brief` write.
  A test asserts that nothing else under `listings/` changes.
- G6 checks every row of the Run contract and the spec's *The chain* and
  *Failures* sections, including the exact *Etsy market search failed:
  \<reason\>* message.

---

### PR 6 — `feat(ui): drive AI Mode and the PRD 68 chain through AI runs`

**About 2,400 lines.** It moves the browser onto runs and retires the old
endpoints. The page head keeps its current text indicator, now fed by run
steps.

**Scope**

- `src/api/aiRuns.ts`: `startAiRun`, `findAiRun(listing)`, `cancelAiRun` and
  `openAiRunStream`.
  - The stream opener reuses `pages/deploy/runStream.ts`'s `fetch`-based SSE
    reader.
  - Pull the reader out into `src/api/sse.ts` if sharing it needs more than
    an extra argument.
- `pages/editor/aiSeo/useAiRun.ts` replaces the request half of
  `useAiSeoMode` and all of `useAutoDesignBrief`. It exposes:
  - the run state as `steps: WorkflowStep[]`;
  - `queries`, `market` and `proposal`;
  - `start({draftBrief})` and `cancel()`;
  - `phase`.
- On mount, it reattaches with `findAiRun` and replays events.
- On a `brief` event with `written`, it sets the field's value without
  marking it dirty.
- On a `proposal` event, it stores the proposal in `aiSeoStorage` and opens
  the drawers, as today.
- Auto chain:
  - The design strip's `onPick` arms it while the brief is empty.
  - It fires once, on the first successful save with a name, design and
    garment profile, using `draftBrief = brief.trim() === ""`.
  - A new pick re-arms it. Unmounting disarms it.
- The AI Mode button calls `start({draftBrief: brief.trim() === ""})`.
- *Generating for X seconds* reads from the run's start time.
- Cancel calls `cancelAiRun`.
- `AiActivityIndicator` keeps its current markup for now. Its label comes
  from the active step. PR 7 replaces it.
- **Retire** `POST /api/ai/design-brief` and `POST …/ai-seo/proposal`:
  - the routes, `ActiveSeoRequests`, `generate_with_cancellation` if nothing
    else uses it, their schemas and tests;
  - `requestDesignBrief` and `requestSeoProposal`.
- Regenerate `openapi.json` and `schema.ts`.
- Update `tests/browser/test_ai_seo_browser.py` for the run-based flow.

**Tests**

- Vitest for `useAiRun`:
  - step reduction;
  - reattach and replay;
  - the brief event: written versus not written;
  - storing the proposal;
  - cancel;
  - the arming and firing rules for the auto chain: fires once, re-arms on
    a new pick, never fires after a failure without a new pick, waits for
    the garment profile.
- The existing `AiSeoControl` and drawer tests are updated.

**Success conditions**

- G1, G2, G3, G4, G5, G6 and G7.
- G5: the Brief row, AI Mode button, *Generating for…* line and Cancel
  behave as in the `researching`, `suggesting` and `ready` frames. A reload
  mid-run shows the same state again.
- There are no references left to the retired endpoints: `rg` finds none in
  `src/`, `tests/` or `docs/openapi.json`.
- Manual check against a real workspace:
  1. Create a listing and pick a design. The chain waits until a garment
     profile is chosen.
  2. It then drafts the brief, and the brief appears in the field.
  3. Suggestions arrive.
  4. Reloading mid-run reattaches.
  5. Cancel stops the run and leaves the brief.

---

### PR 7 — `feat(ui): three-node AI workflow indicator in the page head`

**About 900 lines.** Ports the mocked indicator.

**Scope**

- Move `@phosphor-icons/react` from `devDependencies` to `dependencies`.
- `pages/editor/aiSeo/AiWorkflowIndicator.tsx`:
  - Port it from `design/screens/marketSeo/AiWorkflowIndicator.tsx`. Leave
    out `openTip` and `--tip-open`, which are for the canvas only.
  - It takes `steps` from `useAiRun`.
  - It replaces `AiActivityIndicator` in `ListingEditorPage`'s `activity`
    slot. `AiActivityIndicator` and its test are deleted.
- The 4s fade: once every step is `done` or `skipped`, wait 4s, fade out over
  300ms, then render nothing. `warning` and `failed` states stay until the
  next run or until the editor unmounts. Under `prefers-reduced-motion`, the
  fade is replaced by an instant hide.
- Styles:
  - Port the `.aiflow*` rules from `design/screens/marketSeo/marketSeo.css`
    into `src/index.css`.
  - Move `--seo-purple` and `--seo-pink`, plus a new `--seo-ink: #593baf`,
    to `:root`.
  - Remove the per-selector copies and the literal `#593baf` values
    (a refactor with no visual change).
  - Keep the `aiflow-glow` keyframes and the 3s reduced-motion duration.

**Tests**

- Vitest: every state row in the interactions doc, including labels,
  `aria-label`s, the hover card's content and the badges.
- The fade timer, using fake timers.
- Reduced motion.

**Success conditions**

- G1, G2, G3, G4, G5 and G7.
- G5: compare with every indicator cell in the `states` frame, and with the
  page head in the `researching`, `suggesting` and `ready` frames. Also check
  the hover card's placement at the head's left edge, focus-visible on the
  nodes, and the glow at 1.5s and at 3s under reduced motion.
- After the `:root` token move, the existing AI Mode UI's screenshots are
  pixel-identical.

---

### PR 8 — `feat(ui): top listings panel beside Listing Details`

**About 2,300 lines.** Adds the right-hand panel and its read endpoint.

**Scope**

- Backend: `GET /api/listings/{name}/market` returns the `MarketSnapshot`
  DTO, or 404. It reads through `market/snapshot.py`. Regenerate
  `openapi.json` and `schema.ts`.
- `pages/editor/market/MarketListingsPanel.tsx`, ported from
  `design/screens/marketSeo/MarketListingsPanel.tsx`:
  - **Header and meta:** the relative time comes from `searched_at`.
  - **Searches sentence.**
  - **Switch:** Listings/Phrases, using the app's `.seg` control.
  - **Listings:** *Examples shown to AI Mode* (top 8), then *Show N more
    scored listings*, which reveals *Also scored* and can't be collapsed
    again.
  - **Rows:**
    - rank; a 40px `<img>` thumbnail with `object-fit: cover`, and a neutral
      tile if the image fails to load;
    - a one-line title, the shop with its rating, *Your shop*, metrics, and
      the score and bar;
    - one open row at a time; expanding shows the lead, tags and *Open on
      Etsy*.
  - **Phrases:** ticks follow the phrase-tick rule, recomputed from the
    pending proposal. With no pending proposal there are no ticks, and the
    footnote is hidden.
  - **States:**
    - No snapshot and no run: nothing is rendered.
    - `loading`: from the run's `step market active`. The `queries` event
      fills the sentence.
    - `ready` / `empty`: from the `market` event, or from `GET …/market` on
      mount.
    - `failed`: from `step market failed`. The previous snapshot stays on
      disk, and the panel returns to it on reload.
- `DetailsTab`:
  - Wrap the fieldset and the panel in `.mkt-layout`: `minmax(0,760px)
    300px`, sticky, stacking below 1100px.
  - With no panel, the fieldset keeps its current width.
- Port the `.mkt-*` rules. Delete the canvas-only `.mkt-states*` rules and
  `TeeThumb`.

**Tests**

- API test for the endpoint.
- Vitest for every panel state:
  - row expansion (only one open at a time);
  - show more;
  - switching views;
  - the tick rule: tag, title, lead and case;
  - *Your shop*;
  - a broken thumbnail;
  - the layout with and without a snapshot.
- A browser test: a listing with a seeded snapshot shows the panel after a
  reload.

**Success conditions**

- G1, G2, G3, G4, G5, G6 and G7.
- G5: compare with the panel in the `researching` (loading), `suggesting`
  (ready) and `ready` (expanded row) frames, and with each panel state in
  the `states` frame. The comparison uses real thumbnails instead of the
  stand-ins. Check every hover and focus state in the interactions doc's
  table.
- G6: the endpoint's payload holds everything the panel reads, and nothing
  the spec keeps out (full descriptions are not sent).

---

### PR 9 — `test(e2e): live market search and a full AI run`

**About 700 lines.**

**Scope**

- `tests/e2e/test_market_search_e2e.py`: a real, read-only `research` run
  for one fixed query set.
  - It asserts the shapes, that there are at most 20 scored listings, and
    that there are no writes.
  - It costs about 24 calls, and never writes to the shop.
- `tests/e2e/test_ai_run_e2e.py`: one full AI run through the API
  (`POST /api/ai/runs` → SSE → terminal `done`) with real Etsy search, on a
  fixture listing with an empty brief and `draft_brief=true`.
  - It asserts the step-event sequence, that the brief is written, that the
    snapshot file exists, and that the proposal validates.
  - The AI provider is `FakeAiProvider` by default. `E2E_REAL_AI=1` switches
    to the real Codex/Claude chain. The switch lives in a fixture in
    `tests/e2e/conftest.py`, and its docstring explains the switch.
- `.github/workflows/e2e.yml`: no `E2E_REAL_AI`, so CI always uses fakes.
  Add a comment that says so.
- `AGENTS.md` / test docs: one line on running with real AI locally.

**Success conditions**

- G1, G2, G3, G4 and G7.
- Locally, both e2e tests pass once with `E2E_REAL_AI` unset and once with
  `E2E_REAL_AI=1`, using the developer's signed-in providers.
- On the dispatched GitHub Actions run, both tests ran and passed with fake
  AI: they appear in the log and weren't skipped.

---

## Acceptance for the feature

The feature is done when all of the following are true:

- all nine PRs have merged in order;
- the push-to-`main` e2e workflow is green; and
- a seller can:
  1. create a listing, pick a design and choose a garment, and watch Brief →
     Market research → SEO suggestions run in the page head;
  2. see the top listings fill in beside the fields;
  3. leave and come back to find the run still going;
  4. pick suggestions from drawers worded after the phrases the market
     rewards; and
  5. reload later and still see the panel.

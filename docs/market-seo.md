# Market-informed SEO

Companion to [prd.md](prd.md) (AI Mode: PRD 4, 13 and 68, as amended by PRD 71).
This is the product: how an SEO proposal learns from listings that are already
selling on Etsy, and what that costs. The UI is described in
[ui-market-seo-interactions.md](ui-market-seo-interactions.md), and the build
order in [market-seo-implementation-plan.md](market-seo-implementation-plan.md).

Where this disagrees with the PRD, the PRD wins.

---

## Why

An SEO proposal today is built from the design, the brief and the garment. The
model has no evidence of what buyers actually search for, so `seo.md` has to
tell it not to claim search volume it cannot see. Etsy's Open API cannot give
us search volume either, but it can show us which comparable listings Etsy
ranks and buyers reward. Their titles, tags and description leads are the
closest thing to real buyer vocabulary we can get without another
subscription. eRank has the data but no API.

So market data becomes the **primary driver of wording**: which phrases, in
what order, and how a title is built. It does not decide what is true about the
listing. That stays with the facts, the design text, the image and the brief.

## The chain

Every SEO proposal runs as one **AI run** (see [AI runs](#ai-runs)) of up to
four steps. That includes the run PRD 68 starts automatically.

1. **Brief.** Only when the run asks for a draft (PRD 68's automatic chain),
   and written only into an empty field. When the seller presses AI Mode, the
   brief already exists and this step is skipped.
2. **Query extraction.** A provider call that turns the brief and design into
   three buyer search queries.
3. **Market search.** Read-only Etsy calls that find, filter and score
   comparable listings.
4. **Proposal.** The existing SEO call, with a market-data block added to its
   context.

A failure in step 2 or 3 fails the run. There is no fallback to generating
without market data, because the market data is the primary driver. The brief
from step 1 stays written either way.

## Query extraction

The call has its own seller-editable prompt, `prompts/market-queries.md`,
seeded by `setup` like `seo.md` and `brief.md`. It goes through the same
provider chain as every other AI Mode request: Codex, then Claude Code on a
recognised unavailable failure, and one same-provider repair for malformed
output.

- **Input:** the brief, the design image, and the garment profile's display
  title (for example *Unisex Heavy Cotton Tee*).
- **Output:** exactly three unique, non-empty buyer search phrases, such as
  `retro sunset hiking shirt`. **Each ends in the buyer's word for the item
  type** (*shirt*, *tee*, *hoodie*), taken from the garment. That word does the
  job a taxonomy filter would (see [Search](#search)). The prompt asks for it,
  but validation doesn't check it. It is validated like a brief: a response
  that isn't three usable queries goes through the repair and then fails.
- **Not cached.** Extraction is non-deterministic, and a second request should
  be free to try different queries. Every proposal request extracts afresh.

It is its own step rather than part of the brief draft because a brief the
seller wrote, or one written before this feature, never goes through drafting,
and the SEO chain needs queries either way.

## Market search

### Search

For each query, `findAllListingsActive` with:

| Parameter | Value | Why |
|---|---|---|
| `keywords` | the query | |
| `sort_on` | `score` | Etsy's own relevance ranking, the order a buyer would see. |
| `limit` | 25 | 3 × 25 gives about 60 unique candidates after removing duplicates. |
| `buyer_country` | `US` | Documented as "filters results to listings that ship to this country". The seo prompt targets US buyers. |

There is **no `taxonomy_id`**. No listing or garment profile records an Etsy
taxonomy, and asking the seller for one would be one more field to fill in. The
item type at the end of every query ("… shirt") keeps t-shirts competing with
t-shirts rather than with posters and stickers.

Candidates found by more than one query are merged. The listing keeps its best
(lowest) search position across queries.

### Filters

- **Ships to the US,** applied by the search itself.
- **At least 30 days old,** judged by `original_creation_timestamp`. A younger
  listing's per-day rates are too noisy to score.
- **Our own shop is not excluded.** If one of our listings ranks, it is
  evidence like any other.

**Relaxing.** If no candidates survive, the filter runs once more without the
age filter. If that is still empty, the proposal goes
ahead without market data and shows a *No comparable listings found* warning.
This is the one case that proceeds without market data. It is not an API
failure: the calls worked and there was simply nothing to learn from, and
failing would block every niche design.

### Stats

1. **One batch call:** `getListingsByListingIds` with `includes=Shop,Images`
   for every candidate (at most 100 IDs per call, so one call covers about 60).
   This gives `views` for the listing and its images (the first image's
   170px URL becomes the panel's thumbnail). For its shop, it gives the shop
   name, `transaction_sold_count`, `review_average` and `review_count`.
2. **Preliminary ranking** on the free signals: every weight below except
   reviews, rescaled to sum to 1.
3. **Review counts for the top 20 only:** `getReviewsByListing` with `limit=1`,
   reading just the returned `count`. This is the closest thing to per-listing
   sales the API offers, and the only per-listing call, so it is the one we
   ration.
4. **Final score** over those 20, with every weight.

## Scoring

Each metric becomes a **0–1 percentile within the set being scored**, so a
single viral listing can't swamp the rest and metrics on different scales can
be added together. Ties share the average percentile.

| Metric | Source | Default weight |
|---|---|---|
| Listing reviews | `getReviewsByListing` count | 30 |
| Favourites per day | `num_favorers` ÷ listing age in days | 30 |
| Search rank | best position across queries (inverted: 1st is best) | 20 |
| Views per day | `views` ÷ listing age in days | 10 |
| Shop sales | `transaction_sold_count` | 5 |
| Shop rating | `review_average` (a shop with no reviews in the past year counts as lowest) | 5 |

The weights are starting values, expected to be tuned. They live in a new
workspace file, `settings.yaml`, next to `shop.yaml`:

```yaml
market_seo:
  weights:
    reviews: 30
    favourites_per_day: 30
    search_rank: 20
    views_per_day: 10
    shop_sales: 5
    shop_rating: 5
```

Weights are relative, so they don't need to sum to 100. A missing file or key
falls back to the defaults above.

The UI shows a listing's score as a whole number out of 100: the weighted
percentile sum divided by the total weight, times 100. A listing is marked as
**your shop** when its `shop_id` matches `shop.yaml`'s `etsy.shop_id`.

## What the proposal sees

A delimited market-data block is appended to the proposal context, built from
the 20 scored listings in two parts:

1. **Ranked phrase list.** Each tag used by the scored listings, with the
   number of listings using it and a phrase score (the sum of the scores of the
   listings that use it, normalised to 0–1). The top 40 phrases are listed.
   Code does the counting and weighting, because models are unreliable at
   counting across 20 blocks of text.
2. **Top 8 listings, verbatim:** title, all tags and the description lead (the
   first sentence of the description), in score order. These show the model
   how winning titles and openings are *built*, which the phrase list can't.

This hybrid is deliberate. Summaries make the ranking ours, repeatable and
explainable; raw examples add structure and let the model notice a listing that
crept into the results but doesn't match. Full descriptions are left out: they
cost the most tokens, carry the most copying and prompt-injection risk, and the
proposal only writes a lead.

### Authority

`seo.md`'s ranked input list still decides which **claims** are true: explicit
listing and garment facts, then design text, then the image, then the brief.
Market data moves from last place to a separate role. It is the primary source
of **wording and phrase priority**, and it may introduce plausible audiences
or occasions that nothing above contradicts. For example, `gift for hikers` is
fine on a mountain design, while `personalized` is not unless the listing is
personalizable.

Third-party names in market data get no separate rule. `seo.md`'s existing
third-party-name guidance applies to them exactly as it does to any other
phrase.

Other sellers' text is treated as data, never as instructions, like every other
supplied input.

## Cache

Stored under `.cache/market/`, which is gitignored and fully derivable (PRD 22).

| What | Key | Lifetime |
|---|---|---|
| Search responses | query + the search parameters | 7 days |
| Listing stats (batch fields, review count) | `listing_id` | 7 days |
| Latest snapshot per listing (queries, found and scored counts, when it was searched, the scored listings, the phrase list, the block sent to the model) | listing name | until the next *successful* run replaces it |

The snapshot, `.cache/market/snapshots/{name}.json`, exists so the UI can show
the related listings after a reload. A failed run doesn't replace it. A search
that found nothing comparable does replace it, because that *is* the latest
answer. It moves with the listing on rename and is removed when the listing is
deleted, as `.cache/renders/{name}/` is. It is read-only: the seller can't
edit queries or exclude candidates in this version.

Market research itself writes nothing to `listing.yaml`, `generated.yaml` or
a lockfile. The only listing write in the whole chain is step 1's brief (PRD 4,
as amended by PRD 71).

Because extraction isn't cached, a repeat request usually produces slightly
different queries. The 7-day caches still absorb most of the Etsy calls, since
similar queries return largely the same listings.

## Quota

Etsy's limits are **per app** (per API key), set in the Developer Portal, and
counted over a sliding 24-hour window
([Rate Limits](https://developers.etsy.com/documentation/essentials/rate-limits)).
They aren't fixed numbers the tool can hard-code, and **no budget is stored
anywhere**. Instead:

- Every response carries `x-limit-per-second`, `x-remaining-this-second`,
  `x-limit-per-day` and `x-remaining-today`. When `x-remaining-this-second`
  reaches 0, the next call waits for the next second. `x-remaining-today` is
  logged at debug level.
- Going over a limit returns 429 with `retry-after`, which the retry policy
  honours (see [Failures](#failures)).
- No more than 5 market calls are in flight at once.

| Step | Calls per proposal, with an empty cache |
|---|---|
| Search | 3 |
| Batch stats | 1 |
| Review counts | 20 |
| **Total** | **about 24** |

At the commonly issued 10,000 per day, that's roughly 400 proposals a day if
nothing else used the quota, and more as the cache fills. `plan`, `apply`
and publish share the same per-app limit, and retries count against it too.

## Failures

Etsy calls retry **only transient failures**: 429 (waiting at least as long as
`Retry-After` asks), 5xx, timeouts and network errors. They use the Etsy
transport's existing retry policy (`clients/retry.py`): 4 attempts, with
backoff of 0.5s, 1s and 2s plus jitter. Any other 4xx fails immediately,
since retrying won't fix it.

When the retries run out, the run fails with **"Etsy market search
failed: \<reason\>"**. That message is different from the generic *Try again*,
so the seller can tell an Etsy problem from a model problem.

Query extraction failures follow the existing AI Mode rules (fallback, repair,
*Try again*).

PRD 4's 60-second deadline applies to each provider call (brief, query
extraction, proposal) on its own. Market search has no limit of its own. The
whole run is capped at **3 minutes**; when the cap is reached, the run is
cancelled and fails with a timeout message.

## AI runs

A proposal is no longer one synchronous request. The chain is one server-side
**AI run** per listing, modelled on the plan/apply runs (`ui/runs/`) but with
**its own in-memory registry, and a thread per run**. It never uses the
plan/apply worker thread, so AI work and deploys don't block each other.

```
POST   /api/ai/runs                 {listing, draft_brief} -> 202 AiRunSummary | 409 {active_run} | 409 {reason}
GET    /api/ai/runs?listing=        the listing's current or most recent run, or 404
GET    /api/ai/runs/{id}            AiRunDetail: phase, steps, events so far
GET    /api/ai/runs/{id}/events     text/event-stream; replays after Last-Event-ID
DELETE /api/ai/runs/{id}            cancel; 409 if already terminal
GET    /api/listings/{name}/market  the latest snapshot, or 404
```

- **Readiness.** `POST` checks the same things AI Mode's readiness does, plus
  a garment profile, which the queries need for the item type. An empty brief
  is allowed only when `draft_brief` is true.
- **One per listing.** A second `POST` while one is active returns 409, naming
  the active run. A finished run is kept in memory until the next run for that
  listing replaces it. Nothing survives a server restart.
- **Leaving is not cancelling.** Leaving the editor, reloading, or dropping the
  connection doesn't stop the run. The editor reattaches through
  `GET ?listing=` and replays the events. Only `DELETE` (the **Cancel**
  button) stops it, by terminating the provider subprocess tree. A brief or
  snapshot already written stays.
- **The brief write.** The run re-reads the listing under the listing's
  write lock, which PATCH autosave and rename also take. It writes `brief`
  only if the saved brief is still empty, then emits `brief {text, written}`.
- **Suggestions** still live in browser local storage (PRD 4). The browser
  stores the `proposal` event there. Replay only covers a run that is in
  progress or has just finished.

Events are sent as `event: <type>` / `data: <json>`, each with an `id`:

| Event | Payload | Emitted |
|---|---|---|
| `step` | `{id: "brief"\|"market"\|"seo", state: "pending"\|"active"\|"done"\|"skipped"\|"warning"\|"failed", detail?}` | on every step change, starting with the initial state of all three |
| `brief` | `{text, written}` | once the brief is drafted |
| `queries` | `{queries}` | once the queries are extracted |
| `market` | `{snapshot}` | once a successful or empty search has been saved |
| `proposal` | the validated proposal, unchanged | once the proposal validates |
| `phase` | `{phase: "done"\|"failed"\|"cancelled", message?}` | terminal, always last |

`POST /api/ai/design-brief` and `POST /api/listings/{name}/ai-seo/proposal` are
retired. `GET …/ai-seo/readiness` stays, for the AI Mode button.

## Prompts and `setup --replace-prompts`

The new market-data instructions live in the packaged default `seo.md`, and
`market-queries.md` is a new prompt. `setup` normally only seeds a prompt that
is missing and never overwrites seller content, so an existing workspace would
never get the new instructions.

- **`setup --replace-prompts`** overwrites every prompt in `prompts/` with its
  packaged default. The previous file is kept as `<name>.md.bak`, overwriting
  any older `.bak`. This is a deliberate, opt-in exception to setup's rule that
  it fills gaps and doesn't correct answers.
- **Without the flag,** setup logs a warning for each existing prompt that
  differs from its packaged default. The warning names the file and the flag.
- Workspaces are assumed to have run the flag. Nothing detects an outdated
  `seo.md` at request time.

## UI

The page head shows the run as a three-node workflow indicator: Brief, Market
research, SEO suggestions. Listing Details gains a **top listings panel** on
the right: the related listings with their thumbnail, title, a link to Etsy,
their metrics and score, and the ranked phrase list. It's filled from the
snapshot, so it survives a reload. The design is in
[ui-market-seo-interactions.md](ui-market-seo-interactions.md).

## Testing

- **Unit tests** against a fake Etsy search client in `clients/etsy/fakes.py`:
  scoring and percentiles, weight loading, removing duplicates and taking best
  rank, the age filter, relaxing filters, top-20 rationing, cache expiry, retry
  classification, and assembly of the market-data block.
- **API and run tests** with fake AI providers and the fake Etsy client:
  every step-state sequence, the brief write, cancellation, replay and the
  3-minute cap.
- **One `pytest -m e2e` test** running the live, read-only search for one
  query set. It costs about 24 quota calls and never writes to the shop.
- **One full-run `pytest -m e2e` test:** a whole AI run through the API
  against real Etsy search. It uses fake AI providers by default, which is
  what CI runs. `E2E_REAL_AI=1` switches to the real Codex/Claude chain for a
  local run.

## PRD changes

Recorded in the PRD: #4, #13 and #68 are amended, the setup seeding exception
is added, the config section gains `settings.yaml`, and decision #71 points
here.

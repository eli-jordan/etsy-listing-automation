# Listing template and batch creation specification

**Status:** settled product requirements. The interactions are in
[features/batch-creation-20260927/interactions.md](interactions.md), which
wins over this document where they differ; its reviewed departures have been
applied here. The build is planned in
[features/batch-creation-20260927/plan.md](plan.md).

## Outcome

The seller can capture the reusable production settings of a listing as a
**listing template**, drop up to 25 finished design PNGs onto that template,
review the cleaned names and validation results, and create one ordinary local
listing per design. The application then runs the existing brief, market
research, and SEO proposal chain for those listings through a resumable batch
queue.

The result is a set of local listing drafts ready for human review. Generation
writes a fresh design brief, but title, tags, and description lead remain
suggestions until the seller accepts them. Nothing in batch creation deploys to
Printify or Etsy.

This feature optimises the repeated workflow, not the listing model. Every
created instance is an ordinary listing and follows the same validation,
planning, applying, lifecycle, and idempotency rules as a listing created by
hand.

## Terms

**Listing template** always means the new reusable production configuration.
The qualified name is deliberate: the application already has **mockup
templates**, referenced by `media[].template`, and the two concepts must not be
called simply "templates" in code or UI where they could be confused.

**Staging session** is an uploaded but unconfirmed set of designs, its frozen
listing-template snapshot, validation results, and proposed names.

**Batch** is a confirmed creation job: its frozen listing-template snapshot,
created listing rows, AI queue state, errors, and review status.

**Proposal** is the latest AI-generated title, tag, and description-lead
suggestions for one listing. Accepted values are ordinary listing edits; the
proposal is not listing content.

## Product invariants

1. A listing template is a separate first-class workspace resource, not a
   design-less listing and not a special listing kind. It never appears in
   listing discovery, `plan --all`, `apply --all`, or deployment UI.
2. Instantiation is a snapshot operation. A created listing has no live link to
   its listing template, and later template edits never alter existing staging
   sessions, batches, or listings.
3. One batch uses exactly one listing template. Assigning different templates
   per design and rule-based template routing are out of scope.
4. Batch creation creates local listings only. Review and deployment remain
   separate seller actions.
5. AI generation may write only a fresh brief automatically. Title, tags, and
   description lead still require explicit seller acceptance.
6. All batch writes are retry-safe. A reload, process restart, Resume, or Retry
   must not duplicate a listing row within the same batch.
7. A failed row does not stop unrelated rows. Successful work remains visible,
   and the failed row states what can be retried or corrected.
8. Listing-template, listing, design, and asset paths are resolved only through
   `Workspace`; no API or UI feature independently joins workspace paths.

## Listing templates

### Storage and identity

Listing templates live outside `listings/`, under a workspace layout owned by
`Workspace`, conceptually:

```text
listing-templates/
  heavyweight-tee/
    template.yaml
    assets/
      size-chart.png
```

`ListingTemplate` is its own configuration type. It contains only reusable
production settings; it is not a `Listing` with placeholder fields. Its name is
a single safe path segment and is its workspace identity. Creating or cloning a
template proposes a name but requires the seller to choose a unique one. It
never overwrites or silently suffixes an existing listing template.

Listing templates are ordinary workspace data, not cache data. Listing-local
media copied into a template becomes template-owned data beneath that
template's directory.

### Creation and cloning

The seller can create a listing template in two ways:

1. **Create listing template** from an existing listing.
2. **Clone listing template** from an existing listing template.

There is no blank listing-template creation flow in the first version. Both
operations create an independent snapshot with no continuing source link.

Saving a listing as a template copies these fields:

| Area | Copied content |
|---|---|
| Product | `garment_profile`, `colors` |
| Pricing | `prices`, `pricing_plan`, `price_overrides` |
| Gallery | `media` in its existing order |
| Description body | `etsy.description.text` or `etsy.description.ref` |
| Etsy production settings | `etsy.renewal`, `etsy.section`, `etsy.shipping_profile`, `etsy.variation_images` |

It deliberately excludes or resets these fields:

| Area | Excluded content | Reason |
|---|---|---|
| Artwork | `design`, `artwork` | Every batch row supplies one new complete PNG; per-design artwork routing is not reusable. |
| Generation input | `brief` | The artwork-specific brief is generated afresh for every instance. |
| SEO copy | `etsy.title`, `etsy.tags`, `etsy.description.lead` | Every instance receives its own reviewable proposal. |
| Lifecycle | `lifecycle` | A new instance is a new working listing. |
| Applied/remote state | lockfile, provider IDs, renders, market snapshots, runs, proposals | A template cannot inherit deployment identity or generated state. |

A bare media ref rooted in the workspace remains a shared workspace ref. For
each `./` listing-local image or video, **Create listing template** copies the
file into template-owned assets and rewrites the ref. Instantiation copies that
asset into the new listing so the resulting `./` ref remains listing-local. A
missing or unreadable source asset prevents the listing template from being
saved. Inline `etsy.description.text` is copied deliberately because the seller
chose it as reusable template content; the conversion UI must show it rather
than implying that all prose is being reset.

**Create listing template** has no confirmation dialog. It opens the new
listing template straight away in the listing-template editor, unsaved, with
the name field focused; the editor shows what was kept, and the design-specific
fields are simply absent. Nothing is written until the seller commits a unique
name, and leaving without naming discards the draft. **Clone** opens the same
unsaved state prefilled from the source listing template.

### Completeness and editing

A listing template must be locally complete whenever it exists on disk. Saving
or cloning validates all reusable production facts, including:

- a usable garment profile;
- at least one enabled colour, consistent with price and media overrides;
- a usable pricing source;
- a non-empty, structurally valid gallery;
- resolvable mockup-template, common-copy, pricing-plan, and file refs; and
- every other cross-field rule that can be proven from workspace files.

Design, brief, title, tags, and description lead are intentionally absent and
are not completeness failures. Live provider facts, such as whether a retail
price is above Printify's current cost, remain deployment-time checks. Saving a
listing template never calls a remote provider.

Listing templates have a dedicated editor that reuses the applicable listing
controls while hiding design-specific SEO, lifecycle, and deployment actions.
It autosaves only complete documents. If an edit temporarily makes the client
draft invalid, the server retains the last complete version, the editor keeps
and explains the unsaved values, retries when the document becomes valid, and
warns before navigation would discard them.

The Images experience uses the mockup calibrator's existing test-design
interaction exactly: `bundled-grid` is the default on each load, and the seller
can select another bundled/uploaded test design or upload a new PNG. This is a
way of viewing the listing template, not template metadata and not production
artwork.

Deleting a listing template is allowed even when batches or listings originated
from it. Frozen staging and batch snapshots retain their copy of the listing-
template document and template-owned assets, so they remain usable without the
listing-template directory. Workspace-shared refs such as pricing plans,
common-copy files, and mockup templates remain shared refs and are not frozen;
their ordinary workspace validation and change semantics still apply.

## Starting a batch

### Entry points

The primary flow is a **New batch** page:

1. choose one listing template;
2. drop designs;
3. inspect and edit staging;
4. confirm creation.

Because the expected listing-template library is small, each listing-template
card is also a drop target. Dropping onto a card opens the same staging flow
with that listing template preselected. It never bypasses validation or the
confirmation step.

### Accepted input

One staging session accepts one of two mutually exclusive input modes:

- exactly one ZIP file; or
- one or more loose PNG files.

Multiple ZIPs and a mixture of ZIP and loose PNG files are refused. A ZIP is
vendor-agnostic even though Kittl exports are the motivating case: every PNG at
any directory depth becomes a candidate design. Non-PNG entries are ignored,
and staging shows their count with an expandable name list rather than filling
the main table with them.

The limit is 25 unique PNG designs per staging session. A larger input is
refused before staging rather than truncated or split into implicit batches.
Archive extraction must also enforce bounded compressed and expanded sizes and
reject traversal, symlinks, and other entries that cannot safely become plain
uploaded files. Exact byte ceilings are an implementation safety limit, not a
seller-facing workflow setting.

### Frozen staging

Starting staging freezes the saved listing-template document and its owned
assets. Later template edits and deletion do not change or invalidate the
staging session, and there is no Refresh to latest action. To use newer template
content, the seller starts another staging session.

Staging is a server-side cache resource so an accidental browser reload does
not require another upload. It expires seven days after its last edit. Confirm,
Cancel, expiry, or clearing `.cache` removes temporary ZIP and extracted upload
data once every still-needed row has been materialised. Browser uploads can
never remove the seller's original local files.

## Staging validation and naming

### Design validation

Each candidate is decoded and validated against the frozen listing template's
garment profile using the existing design rules. It must:

- be a readable PNG;
- have an alpha channel; and
- be at least 90% of the garment print area's width and height.

The importer never converts or upscales artwork. Invalid rows show the existing
specific refusal and can be removed so the remaining valid rows may proceed.
Confirm requires at least one valid row. The application checks shared AI
prerequisites before confirmation: required prompts, at least one ready provider,
and Etsy market credentials must all be available so the batch is not knowingly
created into a queue that cannot run. Confirmation also revalidates the frozen
document's workspace-shared refs, since those dependencies may have changed
after staging began.

Multi-artwork instances, including inferred `on-light`/`on-dark` file groups,
are out of scope. Each accepted PNG produces:

```yaml
design:
  default: designs/<name>.png
```

### Cleaning and editing names

The initial base name is the PNG filename stem passed through the existing
`slugify`: lowercase, each run outside `a-z0-9` collapsed to one hyphen, then
leading and trailing hyphens removed. ZIP directory names do not enter the
result. There is no Kittl-specific suffix stripping, transliteration, or custom
cleanup rule. A poor or empty result must be corrected in staging.

One editable base name normally drives both:

```text
designs/<base>.png
listings/<base>/listing.yaml
```

Generated names take the smallest numeric suffix free for both resources,
starting with `-2`. A manually edited name that conflicts during staging is
reported rather than silently changed, with the next available suffix offered
as a suggestion.

Confirmation rechecks names atomically. If another operation claimed a staged
name after the preview was calculated, confirmation allocates a fresh numeric
suffix rather than overwriting or failing the whole batch. The batch summary
shows the final names actually created.

### Content deduplication

PNG bytes, not uploaded names, identify artwork content.

- Identical PNGs within one upload or ZIP collapse to one staged row. The row
  reports the duplicate source names.
- If identical bytes already exist under `designs/`, the new listing reuses the
  existing file rather than writing a duplicate. Its listing name still comes
  from the current staged base name, so this is the named exception where the
  listing and reused design filename differ.
- A different image whose desired path is occupied receives the same numeric
  suffix as its new listing.
- Deduplication of *listing creation* is scoped to the batch. Resuming or
  retrying one batch never duplicates its rows, but intentionally uploading the
  same artwork in a later batch creates new numerically suffixed listings.

## Confirming a batch

Confirmation assigns a stable opaque batch ID and a human-readable label. The
default label combines the listing-template name and date/time -- led by the
ZIP's filename, without `.zip`, when the designs came in one ZIP
(`<zip name> · <listing template> · <date>`), since that name is usually the
collection the seller exported. It is editable before and after creation
without changing batch identity.

The application persists the batch record first, then attempts every valid row.
For each row it:

1. materialises or reuses the production design under `designs/`;
2. copies the frozen listing-template document;
3. sets the new single-file design ref and an empty brief;
4. copies template-owned listing-local media into the listing directory; and
5. writes the ordinary `listing.yaml` with no lockfile or remote identity.

All creatable listings appear before AI processing begins. An unexpected
filesystem failure is recorded against its row and does not roll back or block
other rows. Retry resumes the idempotent row creation from its recorded state.
Only rows whose listing was created enter the AI queue.

## Batch AI queue

### Scheduling

Confirmed batches share one workspace-wide **batch** AI queue. Its concurrency
is `batch_ai.concurrency` in `settings.yaml`, defaults to `1`, and has no settings
UI in the first version. The limit applies across all active batches, not once
per batch. When several batches have work, the scheduler serves them round-robin
so a large batch cannot monopolise the queue.

Manual editor AI runs do not consume this batch limit. However, the manual AI
control is disabled for a listing while that listing has pending or active
batch AI work; two runs must never own one listing.

The queue, row states, and enough ownership information to resume safely live in
`.cache`. A server restart returns interrupted work to a resumable pending state
and continues without creating another listing. Multiple workers must claim a
row atomically.

### Per-row run

Each row runs the existing chain:

1. generate a fresh brief from the design and write it directly to the empty
   `brief` field;
2. derive market queries and research Etsy;
3. generate the SEO proposal; and
4. persist the latest proposal in server-side cache.

Brief writing follows the existing seller-wins rule. The worker rechecks the
field under the listing write lock immediately before writing; if the seller
has supplied text while the row waited, it keeps that text and uses it for SEO
instead of generating over it.

The run freezes its relevant listing inputs. Changes while it runs do not get
silently mixed into that generation; they make the resulting proposal stale.
A pending row uses the listing's current saved values when its turn begins.
Listing rename must update batch and proposal ownership without attributing a
result to the old name. Deleting a listing cancels its work and leaves a deleted
row in the batch summary.

If a row fails, later rows continue. The failed row retains its listing and
design and exposes Retry. If brief generation had already succeeded, Retry
keeps that saved brief, including any seller edits, and reruns the remaining
work rather than replacing it.

### Cancellation and deletion

There is no per-row Cancel action in the first version. **Cancel batch** stops
active and pending AI work but keeps designs, listings, written briefs,
completed proposals, errors, and history. **Resume batch** explicitly queues
the remaining work again.

Deleting a batch record implicitly cancels its work, then removes its summary,
review flags, retry/resume state, and its Recent batches row. It never deletes
designs, listings, written briefs, or proposals.

## Durable AI proposals

Every AI run, whether started by a batch or manually in an editor, writes one
latest proposal to server-side cache. Regeneration replaces the previous
proposal; there is no proposal history. Proposals do not expire automatically.
They remain until replaced, the listing is deleted or fully deployed, or cache
data is cleared.

This replaces browser-local proposal persistence. Existing browser-local
proposals are discarded on upgrade rather than migrated.

The proposal continues to contain the existing ranked title, tag, and
description-lead choices and its frozen input snapshot. Acceptance continues
through ordinary listing-editor fields and autosave. The generated brief is the
only output written without a seller choosing it.

The cache record also owns the proposal's per-field resolution state. Accepted
or dismissed title, tag, and lead sections remain resolved after reload; keeping
the proposal means the seller can still inspect or deliberately reopen those
suggestions, not that resolved drawers repeatedly present themselves as new.

Changes to relevant generation inputs mark the proposal stale. Staleness is
computed by the server, so the batch summary and the editor report it the same
way. A stale proposal remains visible and, unlike the earlier interaction, its
choices stay usable with no confirmation dialog: the drawer heading is the
warning (*Out of date: brief edited since. Still usable*), and **Regenerate**
remains available. This rule applies to every proposal, not only batch
proposals. Staleness must never be hidden or mistaken for current output.

Marking a row Reviewed does not clear its proposal. Renaming a listing moves its
proposal ownership; deleting a listing removes the proposal and cancels an
active run.

## Review workflow

The persistent batch summary is the batch's only dedicated review surface. It
shows the final listing name, creation and AI status, validation or runtime
error, proposal readiness/staleness, and the independent Reviewed flag for each
row. It provides the relevant Resume, Retry, rename-batch, open-listing, and
review-state actions.

The ordinary listings table is unchanged: there is no batch filter, because the
summary already lists and opens every listing in the batch. There is no separate
next/previous batch review editor in the first version.

Batches and unfinished staging sessions are reopened from a **Recent batches**
table on the Listing templates page. Each row shows a status derived from its
rows, never set by hand: *Staging* (not confirmed), *Drafting* (AI work still
queued or running), *In review* (AI finished, not every listing reviewed),
*Complete* (every created listing reviewed) or *Stopped* (**Cancel batch** left
work undrafted). Failures are not a status; they appear as a count beside the
progress. Complete does not require deploying.

**Mark reviewed** and **Mark needs review** are available from both the batch
summary and listing editor. Reviewed is an explicit seller judgment:

- opening a listing does not mark it reviewed;
- accepting every proposal field does not mark it reviewed;
- a later listing edit or regenerated proposal does not reset it;
- a failed AI row may still be marked reviewed after manual completion or an
  intentional decision not to use AI; and
- review state is advisory and never blocks `plan` or `apply`.

Review and batch membership live in disposable cache. Clearing `.cache` removes
batch history, queue state, Reviewed flags, staging sessions, and
unaccepted proposals. It does not remove listing templates, designs, listings,
generated briefs, accepted SEO edits, lockfiles, or remote state.

## Deployment interaction

Batch creation never deploys. A created listing becomes deployable only after
ordinary listing validation passes, including a seller-accepted non-empty title
and description lead.

If a UI deploy (plan or apply) starts for a listing with pending batch work or
any active AI run, deployment takes precedence. The server claims the listing,
cancels the work, and waits for its worker to finish before planning reads the
listing or any remote write begins. It also refuses a new AI run while the
deploy owns the listing. Cancelled batch work must not later resume
automatically and place a proposal onto the deployed listing; only an explicit
Retry of that row queues it again.

CLI `apply` does not cancel or wait for AI work. The AI queue lives in the `ui`
server process, and a CLI apply during batch AI is an accepted edge: the run may
leave a proposal on the deployed listing, which the seller can ignore or
regenerate.

After the full apply for a listing succeeds, every apply entry point removes
that listing's cached proposal. **Full success** means the engine's outcome for
the listing is `ok`, no stage in its plan was blocked, and its lockfile carries
no incomplete-apply marker. `ok` alone is not enough, because a blocked stage is
not a failure; nor is an entry-point command merely returning normally.
The batch record remains, and deployment does not change the explicit Reviewed
flag.

This cache cleanup is an entry-point-independent lifecycle rule, not UI-only
behavior. A CLI apply and UI apply must leave the same proposal state.

## Required UI surfaces

| Surface | Required behavior |
|---|---|
| Listing editor | **Create listing template**; durable proposal review; stale choices usable under an *Out of date* heading; Back to batch when opened from a batch summary; Mark reviewed/needs review when the listing belongs to a cached batch. |
| Listing templates page | Small card collection; open editor; clone; delete; start a batch; accept a drop as a shortcut to staging; Recent batches with derived status. |
| Listing-template editor | Valid-only autosave, production settings, copied media assets, calibrator test-design preview controls, and **Clone** and **Delete** for a saved template. |
| New batch page | Select one listing template, upload one ZIP or loose PNG set, persist and resume staging, edit names, remove invalid rows, confirm. |
| Batch summary | Rename, status counts and rows, Cancel/Resume, Retry failures, open listing, Mark reviewed/needs review, delete batch record. |

## Error and recovery rules

| Failure | Required outcome |
|---|---|
| Invalid ZIP or unsafe entry | Refuse the upload without extracting unsafe content. |
| More than 25 unique PNGs | Refuse before staging; never truncate silently. |
| Unreadable, opaque, or undersized PNG | Keep an invalid staging row with the existing precise design error; allow removal. |
| Empty or poor slug | Require an editable valid name before confirmation. |
| Name occupied during staging | Show the conflict and suggest the next suffix. |
| Name claimed immediately before confirmation | Allocate a free suffix atomically and report the final name. |
| Missing AI prerequisite | Block confirmation before creating listings. |
| One listing creation fails | Record that row, create the others, retain enough input to Retry. |
| One AI run fails | Record that row, continue the queue, retain listing/design/brief, expose Retry. |
| Browser reload during staging | Reattach to the cached staging session. |
| Server restart during batch AI | Reclaim interrupted rows safely and resume subject to the configured limit. |
| Listing renamed | Follow the current listing name in batch and proposal state. |
| Listing deleted | Cancel its AI, remove its proposal, retain a deleted batch row. |
| Batch deleted | Cancel its work and remove only cache-owned grouping/workflow state. |
| Cache cleared | Keep durable workspace content; lose staging, batch workflow, review flags, and unresolved proposals. |

## Out of scope

The first version does not include:

- an inbox directory, filesystem watcher, startup scan, or folder-processing
  CLI command;
- a CLI batch-creation surface;
- more than one listing template per batch;
- automatic or rule-based template selection;
- mixed ZIP and loose-PNG input, or multiple ZIPs in one batch;
- multi-artwork grouping such as `on-light` and `on-dark` designs;
- Kittl-specific filename heuristics beyond ordinary slugification;
- automatic acceptance of AI title, tags, or description lead;
- automatic deployment to Printify or Etsy;
- a hard deployment gate based on disposable Reviewed state;
- proposal history or automatic proposal expiry;
- individual row cancellation;
- a settings UI for batch concurrency;
- live-linked or explicitly versioned listing templates;
- a batch filter on the listings table; or
- CLI `apply` cancelling or awaiting AI work.

An inbox may be added later as another producer of the same staging resource. It
must not introduce a second naming, validation, deduplication, or batch-creation
path.

## Documentation changes

The earlier authority and interaction documents specified temporary
browser-local proposals and prohibited accepting stale choices. ADR-0047 changes
both. The [ADRs](../../adr/README.md) record the amended proposal lifecycle
and batch boundaries (ADR-0003, ADR-0044 and ADR-0047 through ADR-0051).
The current feature documents are
[features/ai-seo-20260922/plan.md](../ai-seo-20260922/plan.md); and
[features/ai-seo-20260922/interactions.md](../ai-seo-20260922/interactions.md).

The naming allocator does not weaken the no-overwrite rule. It chooses a
free identity before creation; it never merges into or replaces an existing
listing.

## Acceptance criteria

The feature is complete when all of the following are observable:

1. A complete listing can be saved as an independently editable listing
   template, including copies of its listing-local gallery assets, without
   retaining design-specific SEO copy, artwork routing, lifecycle, or remote
   state.
2. Listing templates never appear in listing discovery or any deployment batch.
3. Dropping one ZIP or a set of loose PNGs yielding at most 25 unique designs
   creates a reload-safe staging session with recursive ZIP discovery, existing
   design validation, content dedupe, editable slugs, and collision previews.
4. Confirm creates one ordinary local listing per valid unique row, creates no
   remote state, and continues past a row-specific write failure.
5. Restarting or resuming a confirmed batch cannot create a second listing for
   an already-created row.
6. Batch AI honours the workspace-wide configured concurrency and round-robin
   scheduling across batches, resumes after restart, and continues after one
   row fails.
7. Every successful row has a fresh saved brief, unless the seller supplied one
   before drafting, and one latest server-cached SEO proposal; accepted title,
   tags, and lead still require seller actions.
8. A stale proposal is clearly labelled as out of date and its choices remain
   usable without a confirmation dialog.
9. Batch summary, Recent batches with derived status, Retry, Cancel/Resume, and
   explicit Reviewed controls survive browser and server restarts while cache
   remains.
10. Clearing cache has exactly the documented losses and never removes created
    workspace listings, designs, accepted copy, or deployment state.
11. A UI deploy cancels pending batch work and any active AI run for the listing
    and awaits its termination before planning; UI and CLI apply both clear the
    cached proposal only after the listing's full apply succeeds.

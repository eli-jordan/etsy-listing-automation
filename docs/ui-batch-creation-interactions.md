# Batch listing creation UI flows and interactions

Status: interaction design agreed through four review rounds of mockups. This
document accompanies the frames in
[`src/etsy_listings/ui/frontend/design/scenes/batch-create-lofi/`](../src/etsy_listings/ui/frontend/design/scenes/batch-create-lofi/)
on the **Batch Listing Creation** board.

It explains what the seller does, what the interface does in response, and why.
The product requirements are in
[listing-batch-creation-spec.md](listing-batch-creation-spec.md); this document
does not repeat them, but it does record the places where the reviewed designs
deliberately depart from that spec (see [Departures from the spec](#departures-from-the-spec)).
Where the two still disagree and this document is silent, the spec wins, and
[prd.md](prd.md) wins over both.

Paths below are relative to the repository root. `mockups/` is shorthand for
`src/etsy_listings/ui/frontend/design/scenes/batch-create-lofi/`, and `app/`
for `src/etsy_listings/ui/frontend/src/`.

## Viewing the mockups

1. From `src/etsy_listings/ui/frontend`, run `npx marver dev` and open the
   printed URL.
2. Choose the **Batch Listing Creation** board. The top band is the flow
   diagram; the bottom band holds every screen, left to right in flow order.
3. Press **P** for play mode to click through the screens. Yellow sticky notes
   beside some frames explain mechanisms the screen cannot show.
4. Earlier rounds are on the **Archive** board as `batch-create-lofi-v1` to
   `-v3`.

The frames are hi-fi: the listing and template editors mount the app's real
components over a fixture API (see [Mockup infrastructure](#mockup-infrastructure)),
so what you see is what those components render today, plus the changes this
document lists.

## Flow at a glance

```text
Listing editor ──Save as listing template──▶ New listing template (name it)
                                                   │
                                                   ▼
                                         Listing templates page
                              ┌──────────────┼───────────────────────┐
                    drop files on a card   New batch /          Recent batches
                              │            Start batch          (click a title)
                              │               │                      │
                              │               ▼                      │
                              │      New batch: pick template,       │
                              │      drop ZIP or PNGs ──refused──▶ error, stay
                              ▼               │                      │
                        Staging review ◀──────┘◀── Staging row ──────┤
                              │                                      │
                       Create N listings                              │
                              ▼                                      │
                        Batch summary ◀──── any other status row ────┘
                              │   ▲
                         Open │   │ Back to batch
                              ▼   │
                      Listing editor (from a batch)
```

Nothing in this flow deploys. Every created listing is an ordinary local draft
that the seller reviews and deploys through the existing deploy flow.

## 1. Creating a listing template

**Entry point.** A **Save as listing template** button in the listing editor
(shown in the [listing from a batch](#8-a-listing-opened-from-a-batch) frame,
and present on every listing).

**What happens.** The click creates the template straight away from the
listing's reusable settings and opens it in the listing-template editor, with
the cursor in an empty name field
([`template-new`](../src/etsy_listings/ui/frontend/design/scenes/batch-create-lofi/template-new.tsx)).

Not obvious from the designs:

- **There is no confirmation dialog.** An earlier round had a dialog listing
  what is kept and what is reset; review found it too wordy. The editor itself
  shows what was kept: design-specific fields (brief, title, tags, description
  lead) simply aren't there.
- **Nothing is written until the template has a name.** The head reads *Not
  saved — name this template to save it*. The name must be unique and is never
  silently suffixed; a clash is refused inline by the same `EditableName`
  behaviour listings use for *that name is already taken*.
- **Leaving without naming discards the draft template.** No template exists on
  disk until the name is committed.
- **Clone** on a template card opens the same *name it to save* state, prefilled
  from the source template rather than a listing.

## 2. The Listing templates page

Frame: [`templates`](../src/etsy_listings/ui/frontend/design/scenes/batch-create-lofi/templates.tsx).
A new **Listing Templates** item in the sidebar leads here.

### Template cards

Each card shows the template's gallery, garment, colour count, pricing plan and
how many batches have used it. Its footer holds **Start batch**, **Edit**, and
icon buttons for **Clone** and **Delete**. These are the only places those
actions live: the template editor deliberately has none.

Not obvious from the designs:

- **Every card is a drop target.** The first card in the frame is drawn
  mid-drag: while files are dragged over a card, the whole card becomes the
  target and says what will happen (*Drop to stage 14 PNGs with
  heavyweight-tee*). The overlay only exists during a drag.
- **Dropping on a card skips the New batch page** and lands directly on
  staging with that template chosen. It never skips staging: nothing is created
  until the seller confirms there.
- The same input rules apply as on New batch (one ZIP or loose PNGs, at most 25
  designs). A refused drop shows the New batch page's refusal state.
- **Deleting a template does not affect batches or listings made from it.**
  Staging sessions and batches keep their own frozen copy of the template.

### Recent batches

A table of batches with a derived **Status** per batch. Clicking a batch title
(or anywhere on the row) opens it:

| Status | Meaning | Opens |
|---|---|---|
| Staging | Uploaded but not confirmed; nothing created yet | Staging review |
| Drafting | Listings created, AI queue still working on some | Batch summary |
| In review | AI finished, but not every listing is marked reviewed | Batch summary |
| Complete | Every created listing is marked reviewed | Batch summary |
| Stopped | **Cancel batch** left work undrafted | Batch summary (Resume there) |

Not obvious from the designs:

- **Status is derived, never set by hand.** Marking the last listing reviewed
  moves the batch to Complete; marking one back to *needs review* moves it back
  to In review.
- **Complete does not require deploying.** It means only that every listing has
  been reviewed, because the spec keeps review and deployment independent.
- **Failures are not a status.** They appear as a red count beside the progress
  (*2 need retry*), so a batch with one failed row still reads as Drafting or
  In review rather than hiding its review progress.
- **An unfinished staging session is just a Staging row.** This replaced a
  resume banner on the New batch page. Staging is kept on the server for seven
  days after its last edit, and the row says when it expires.

The status rules are also in the sticky note
[`templates.note.md`](../src/etsy_listings/ui/frontend/design/scenes/batch-create-lofi/templates.note.md).

## 3. Editing a listing template

Frames: [`template-variants`](../src/etsy_listings/ui/frontend/design/scenes/batch-create-lofi/template-variants.tsx),
[`template-pricing`](../src/etsy_listings/ui/frontend/design/scenes/batch-create-lofi/template-pricing.tsx),
[`template-images`](../src/etsy_listings/ui/frontend/design/scenes/batch-create-lofi/template-images.tsx),
[`template-details`](../src/etsy_listings/ui/frontend/design/scenes/batch-create-lofi/template-details.tsx),
[`template-unsaved`](../src/etsy_listings/ui/frontend/design/scenes/batch-create-lofi/template-unsaved.tsx).

The template editor is the listing editor with the design-specific parts
removed. It has the same head layout, design row, tab bar and tabs (Variants,
Pricing, Listing Images, Listing Details). Variants, Pricing and Listing Images
are the real listing tabs, unchanged.

Not obvious from the designs:

- **The design row picks a preview design, not artwork.** It reads *Preview
  design: Bundled grid* and uses the calibrator's test designs (bundled or
  uploaded), plus recent workspace designs. The choice only changes how the
  Variants and Listing Images previews look. It is not saved with the template,
  and it resets to Bundled grid every time the editor opens. Each listing in a
  batch gets its own design.
- **Rename by double-clicking the name**, exactly like a listing.
- **Autosave only writes complete templates.** If an edit makes the template
  incomplete (the frame switches every colour off), nothing is written. The head
  says *Not saved — fix the highlighted field and it will be written*, a banner
  names the problem and says the last complete version is kept, and the
  affected tab carries a count badge. Fixing the problem saves automatically.
  Navigating away with unsaved values warns first.
- **Listing Details has no Brief, Title, Tags, Description lead or AI Mode.**
  Those are written for each listing in a batch. A hint says each listing's own
  lead is placed above the template's description body.
- **The head has no actions.** No status, Deploy, Clone, Delete or Start batch.
  A template never deploys, and the other actions live on the template cards.

## 4. Starting a batch: New batch

Frames: [`new-batch`](../src/etsy_listings/ui/frontend/design/scenes/batch-create-lofi/new-batch.tsx)
and the error state [`staging-refused`](../src/etsy_listings/ui/frontend/design/scenes/batch-create-lofi/staging-refused.tsx).

1. **Listing template.** Pick exactly one. Every design in the batch gets its
   settings.
2. **Designs.** Drop one ZIP or any number of loose PNGs, or choose files.

Not obvious from the designs:

- **Every PNG in a ZIP counts, at any folder depth.** Kittl exports work as they
  are. Non-PNG entries are ignored and listed later in staging.
- **The upload is checked before anything is staged.** More than 25 unique
  designs, more than one ZIP, a mix of ZIP and loose PNGs, or an unsafe archive
  is refused outright. The refusal says what was wrong and how to fix it
  (*Split the export into two ZIPs…*), and confirms nothing was uploaded or
  changed. It never truncates or splits the input silently.
- The size requirement shown under the drop zone comes from the chosen
  template's garment print area, so it changes with the template.

## 5. Staging review

Frames: [`staging`](../src/etsy_listings/ui/frontend/design/scenes/batch-create-lofi/staging.tsx)
and the blocked state [`staging-blocked`](../src/etsy_listings/ui/frontend/design/scenes/batch-create-lofi/staging-blocked.tsx).

One row per unique design, with its source file name, an editable listing name
and a check result. A count strip summarises ready, blocked, not-created,
merged and ignored files. The batch label is editable here and later.

Not obvious from the designs:

- **One name drives two paths**: `listings/<name>/` and `designs/<name>.png`.
  The initial name is the file name slugified. Folder names inside a ZIP are
  dropped.
- **Automatic suffixes.** A generated name that is taken gets the smallest free
  `-2`, `-3`… and says so (*after-rain-trail is taken, so -2 was added*).
- **A name the seller types that is taken is not changed for them.** It is
  flagged, with a one-click suggestion (*Use moss-and-miles-2*). An empty result
  (a file called `★★★.png`) must be typed. **These name problems block Create**;
  the button stays disabled and the page says *Fix 2 names to create the
  listings*.
- **Invalid PNGs do not block Create.** An opaque or undersized design is shown
  as *Not created* with the exact reason, and the button counts only creatable
  rows. Removing the row is optional tidying.
- **Duplicates are detected by content, not name.** Identical files in one
  upload become one row listing both sources. A file identical to one already
  in `designs/` reuses that file, the one case where the listing name and the
  design file name differ.
- **AI readiness is only mentioned when it fails.** When prompts, a provider
  and Etsy market access are all available, nothing is said. When one is
  missing, a blocking callout appears and Create is disabled (wording in
  [`staging.note.md`](../src/etsy_listings/ui/frontend/design/scenes/batch-create-lofi/staging.note.md)).
- **The template is frozen when staging starts.** The page says *Using
  heavyweight-tee as saved at 11:38*. Later edits to the template don't reach
  this batch; there is no refresh.
- **Staging survives a reload.** It lives on the server until seven days after
  its last edit, and appears in Recent batches as a Staging row.
- **Cancel staging** discards the session and returns to New batch. The seller's
  original files are never touched.

## 6. Confirming

**Create N listings** creates every listing before any AI work starts, then
opens the batch summary.

Not obvious from the designs:

- If another operation claims a staged name between review and confirm, the
  listing gets the next free suffix instead of failing. The summary shows the
  final names.
- A filesystem failure on one row is recorded on that row (*not created*, with
  Retry) and does not stop the others.

## 7. The batch summary

Frame: [`batch-summary`](../src/etsy_listings/ui/frontend/design/scenes/batch-create-lofi/batch-summary.tsx).

The batch's only review surface. A progress bar and count strip sit above a
row per listing, showing AI drafting, the SEO proposal, and the Reviewed flag.

Not obvious from the designs:

- **Rename the batch by double-clicking its label**, the same interaction as a
  listing name. Renaming doesn't change the batch's identity.
- **Drafting runs one listing at a time by default**, shared across all active
  batches in round-robin order. **Work continues if the tab is closed**, and a
  server restart resumes it.
- **Running and failed rows show the editor's own AI step indicator** (Brief →
  Market research → SEO suggestions), so a batch row and an open editor read
  the same way. Finished rows show a plain *done* line instead, matching the
  editor, which hides the indicator once a run completes.
- **The brief is written for the seller; title, tags and lead are not.** They
  wait as suggestions to accept in each listing. If the seller writes a brief
  before a row's turn comes, the AI keeps it and uses it.
- **Retry keeps everything that already succeeded.** A row whose market
  research failed keeps its saved brief (including any edits) and reruns only
  research and SEO. A row that was never created retries creating it.
  **Retry 2 failed** retries every failed row at once.
- **Stale proposals** are flagged in the SEO column (*Stale: brief edited
  since*) but stay usable. See [section 8](#8-a-listing-opened-from-a-batch).
- **Mark reviewed is the seller's own judgement.** Opening a listing or
  accepting every suggestion doesn't mark it. Later edits don't reset it. A
  failed row can still be marked after finishing it by hand. It never blocks
  deploying. It is offered only on rows the seller can review: not on queued,
  drafting, deleted or never-created rows.
- **Cancel batch** stops pending and running AI work but keeps every listing,
  brief and proposal already written. The batch becomes Stopped, and **Resume**
  queues the remainder again. There is no per-row cancel.
- **Deleting a listing** cancels its AI work and leaves a struck-through
  *deleted* row.
- **Delete batch record** removes only the batch's own history, flags and
  queue state. It never deletes listings, designs, briefs or proposals.

## 8. A listing opened from a batch

Frame: [`listing-from-batch`](../src/etsy_listings/ui/frontend/design/scenes/batch-create-lofi/listing-from-batch.tsx).

The ordinary listing editor, opened on Listing Details, with a row above the
head holding **Back to batch …**, **Save as listing template** and **Mark
reviewed**.

Not obvious from the designs:

- **Back to batch only appears when the editor was opened from the batch
  summary.** Opening the same listing from the Listings page shows the normal
  editor without it. Save as listing template is on every listing.
- **Mark reviewed** here and on the summary set the same flag.
- **An out-of-date suggestion can be used directly.** The drawer heading reads
  *Out of date: brief edited since. Still usable*, and the choices stay
  clickable. There is no confirmation dialog: the heading is the warning.
  **Regenerate** is still available for fresh suggestions.
- **Deploying takes precedence over AI.** Starting a deploy on a listing with
  queued or running batch work cancels that work first, and the work never
  resumes onto the deployed listing. After a fully successful deploy, the
  listing's cached proposal is removed.

## Departures from the spec

Review changed these decisions after
[listing-batch-creation-spec.md](listing-batch-creation-spec.md) was written.
The spec (and, per its own list, the PRD) should be amended to match.

| Spec says | Mockups do | Why |
|---|---|---|
| Listings table gains a batch filter | No filter; the batch summary is the review surface | The summary already lists and opens every listing |
| Stale proposals accepted only after an explicit warning confirmation | Usable directly; the drawer heading is the warning | A dialog for every stale pick was friction without new information |
| (unspecified) where past batches live | **Recent batches** table with derived status on the Listing templates page | Staging and batches need a place to reopen from |
| (unspecified) Save as listing template interaction | Opens the new template straight away, name field focused | The editor itself shows what was kept |

## Existing screens that change

### App sidebar

A **Listing Templates** item between Listings and Mockup Templates.

- Mockup: [`mockups/_Shell.tsx`](../src/etsy_listings/ui/frontend/design/scenes/batch-create-lofi/_Shell.tsx), the `Shell` component (nav item at line 57).
- App code: [`app/shell/AppShell.tsx`](../src/etsy_listings/ui/frontend/src/shell/AppShell.tsx), the `sidebar__nav` block (lines 33–82).

### Listing editor

Three additions, shown in the `listing-from-batch` frame:

1. **A row above the head** with Back to batch (only when opened from a batch),
   Save as listing template (always) and Mark reviewed (only for a listing in
   a cached batch). The head itself is unchanged: breadcrumb, `EditableName`,
   status, save line and Deploy.
   - Mockup: [`mockups/_ListingEditor.tsx`](../src/etsy_listings/ui/frontend/design/scenes/batch-create-lofi/_ListingEditor.tsx), `ListingFromBatch` (row at lines 71–84; head markup copied from `EditorHead`).
   - App code: `EditorHead` in [`app/pages/ListingEditorPage.tsx`](../src/etsy_listings/ui/frontend/src/pages/ListingEditorPage.tsx) (line 245); the row sits above `ListingEditorShell` (line 296).
2. **Stale suggestions stay usable.** Today the drawer disables its choices
   and says *Suggestions are out of date*. The mockup applies the new heading
   and re-enables the choices on top of the real drawer (the `useEffect` at
   lines 27–49 of `_ListingEditor.tsx`).
   - App code: [`app/pages/editor/aiSeo/AiChoiceDrawer.tsx`](../src/etsy_listings/ui/frontend/src/pages/editor/aiSeo/AiChoiceDrawer.tsx) lines 52 and 61 (`disabled={stale}`), and the same pattern in [`AiTagsDrawer.tsx`](../src/etsy_listings/ui/frontend/src/pages/editor/aiSeo/AiTagsDrawer.tsx) lines 49 and 55.
3. **Proposals persist server-side.** This isn't visible in a frame, but it is
   what lets a batch run's suggestions be waiting when the editor opens. It
   replaces `aiSeoStorage`'s browser-local proposal store (see the spec's
   *Durable AI proposals*).

### Listings page

Unchanged. The batch filter was designed, then dropped in review.

## Existing components the template editor needs

The template editor reuses the listing editor's components. Five need a small
change, all recorded in
[`template-variants.note.md`](../src/etsy_listings/ui/frontend/design/scenes/batch-create-lofi/template-variants.note.md):

| Component | Change | Mockup stand-in |
|---|---|---|
| `DesignSelect` ([app/pages/editor/DesignSelect.tsx](../src/etsy_listings/ui/frontend/src/pages/editor/DesignSelect.tsx)) | Preview wording and a preview-design list (test designs + recent designs) | `PreviewDesign`, `_TemplateEditor.tsx` line 41 |
| `MediaLocator` ([line 141](../src/etsy_listings/ui/frontend/src/pages/editor/MediaLocator.tsx)) | Files group *This listing* → *This template* | Not visible: the frame opens on Mockup templates |
| `IssuesBanner` ([lines 82–95](../src/etsy_listings/ui/frontend/src/pages/editor/IssuesBanner.tsx)) | Template wording: *to fix before this template saves*, *Last complete version is kept until then*, no *Prevents deploying* tag | Banner markup at `_TemplateEditor.tsx` line 209 |
| `DetailsTab` ([app/pages/editor/DetailsTab.tsx](../src/etsy_listings/ui/frontend/src/pages/editor/DetailsTab.tsx)) | A template mode without Brief, Title, Tags, Description lead, AI Mode or the market panel | `TemplateDetailsTab`, `_TemplateEditor.tsx` line 93 |
| `AiChoiceDrawer` / `AiTagsDrawer` | Stale choices usable (listing editor, above) | `_ListingEditor.tsx` lines 27–49 |

`VariantsTab`, `PricingTab`, `ImagesTab`, `EditableName`, `DescriptionSourcePicker`
and the `metaFor` save line are used unchanged (`_TemplateEditor.tsx` lines
195–273).

## New screens

Every frame file is a small harness: it sets `meta` for the canvas and mounts a
shared component with one prop for its state. The component files start with
`_` (marver infrastructure, never a frame).

| Screen | Frame (file in `mockups/`) | Built from |
|---|---|---|
| Listing template, new (name it) | `template-new.tsx` | `TemplateEditor mode="new"`, [`_TemplateEditor.tsx`](../src/etsy_listings/ui/frontend/design/scenes/batch-create-lofi/_TemplateEditor.tsx) line 169 |
| Listing template, Variants | `template-variants.tsx` | `mode="variants"` (preview-design picker open) |
| Listing template, change not saved | `template-unsaved.tsx` | `mode="unsaved"`, fixture `incompleteTemplate` in `_editorFixtures.ts` line 62 |
| Listing template, Pricing | `template-pricing.tsx` | `mode="pricing"` |
| Listing template, Listing Images | `template-images.tsx` | `mode="images"` |
| Listing template, Listing Details | `template-details.tsx` | `mode="details"` → `TemplateDetailsTab` |
| Listing templates page | `templates.tsx` | Inline; `BatchStatusTag` at line 16, drop overlay at line 89, Recent batches at line 108 |
| New batch | `new-batch.tsx` | `NewBatchPage`, [`_NewBatch.tsx`](../src/etsy_listings/ui/frontend/design/scenes/batch-create-lofi/_NewBatch.tsx) line 8 |
| New batch, upload refused | `staging-refused.tsx` | `NewBatchPage refused` (callout at line 50) |
| Staging review | `staging.tsx` | `StagingPage`, [`_Staging.tsx`](../src/etsy_listings/ui/frontend/design/scenes/batch-create-lofi/_Staging.tsx) line 87; row checks in `Check` (line 46) |
| Staging, names need fixing | `staging-blocked.tsx` | `StagingPage blocked`; the two name problems are made in `rowsFor` (line 17) |
| Batch summary | `batch-summary.tsx` | Inline; `AiCell` (line 33) mounts the real `AiWorkflowIndicator`; batch label is the real `EditableName` (line 108) |
| Listing opened from a batch | `listing-from-batch.tsx` | `ListingFromBatch`, [`_ListingEditor.tsx`](../src/etsy_listings/ui/frontend/design/scenes/batch-create-lofi/_ListingEditor.tsx) line 24, around the real `ListingEditorShell` |

The flow diagram is
[`design/scenes/batch-create-specs/flow.tsx`](../src/etsy_listings/ui/frontend/design/scenes/batch-create-specs/flow.tsx),
with the scene brief in `_brief.md` beside it.

## Mockup infrastructure

| File (in `mockups/`) | Role |
|---|---|
| [`_mockApi.ts`](../src/etsy_listings/ui/frontend/design/scenes/batch-create-lofi/_mockApi.ts) | Replaces `fetch` so the real editor components get fixture answers for every `/api` call (`jsonFor`, line 133), and points `/api` image URLs at local assets (`fixturePicture`, line 169). **It must be the first import** of any module that mounts app components, because the app's API client captures `fetch` when it loads. Nothing leaves the frame. |
| [`_editorFixtures.ts`](../src/etsy_listings/ui/frontend/design/scenes/batch-create-lofi/_editorFixtures.ts) | `ListingDetail` fixtures for the template (`templateDetail`, line 16), the incomplete template (line 62) and the batch listing (line 95), plus the hand-set AI Mode state `staleAiSeo` (line 153). |
| [`_fixtures.ts`](../src/etsy_listings/ui/frontend/design/scenes/batch-create-lofi/_fixtures.ts) | Plain fixtures for the new screens: templates, recent batches and their `BatchStatus` (line 67), staging rows (line 130), batch rows (line 190), thumbnail art (`artFor`, line 19). |
| [`_Shell.tsx`](../src/etsy_listings/ui/frontend/design/scenes/batch-create-lofi/_Shell.tsx) | The app shell with the new nav item, around the real `ShellSidebar`. |
| [`_batch.css`](../src/etsy_listings/ui/frontend/design/scenes/batch-create-lofi/_batch.css) | Styles for the new surfaces only (cards, drop zone, counts, status cells), all built from the app's tokens. Tables use the app's own `table.listings`. |
| `design/assets/batch-create/` | Fixture design artwork (SVG) and the size chart. Mockup photos come from `design/assets/batch-deploy/`. |

## Open questions

1. **Recent batches placement.** It sits on the Listing templates page because
   the spec names no batch index. If batches grow in number, they may want their
   own page.
2. **Refused drop on a card.** A drop on a template card that breaks the input
   rules is drawn as returning to New batch with the refusal shown; an inline
   refusal on the card itself was not explored.

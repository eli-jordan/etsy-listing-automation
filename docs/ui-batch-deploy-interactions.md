# Batch deploy UI flows and interactions

Status: settled interaction design. This document accompanies the batch deploy
frames in
[`src/etsy_listings/ui/frontend/design/scenes/batch-deploy-lofi/`](../src/etsy_listings/ui/frontend/design/scenes/batch-deploy-lofi/).

This document describes what the seller does, what the interface does in
response, and why each interaction exists. It extends the individual-listing
deploy behavior in [deploy-changes.md](deploy-changes.md) to the all-listings
case. It does not replace the product decisions in [prd.md](prd.md); where the
documents disagree, the PRD wins.

## Purpose

The seller can already plan and apply one listing. Batch deploy exposes the
engine's all-listings behavior in the UI so the seller can:

1. see the scale of pending work from the Listings page;
2. generate one current plan across the whole workspace;
3. review the plan at both run and individual-listing level;
4. apply exactly the reviewed work; and
5. follow progress without having to keep the page open.

The UI reuses the individual deploy step strip and before/after comparison. A
batch deploy is not a different kind of deploy; it is the same planning and
application model with an all-listings scope and an aggregate progress view.

## Product invariants

These rules are more important than any particular layout detail.

### All means all

Starting a batch plan requests the semantic equivalent of `plan --all`. The
browser does not enumerate listing names and send a client-selected target
list. The backend resolves the workspace's current listings when the run
starts.

Why: a client-side list can become incomplete between loading Listings and
starting the plan. The all-listings command is already the source of truth for
scope and must remain so in the UI.

### Planning is read-only

Opening **Review all changes** reads local, Printify, and Etsy state and builds
a plan. It does not write to Printify, Etsy, listing files, or lockfiles.

Why: the seller must be able to inspect the complete effect before authorizing
remote changes.

### Apply uses the reviewed plan

The apply request carries the expected fingerprint for every reviewed listing.
The engine re-plans before writing and refuses a listing whose plan has changed.

Why: remote drift or a local edit between review and apply must never result in
an unreviewed write.

### Writes remain sequential

Apply runs one stage at a time, one listing at a time. The UI may update many
aggregate counters, but it must not imply parallel writes.

Why: this preserves the engine's sequential-write guarantee and makes progress,
failures, and resumption understandable.

### Batch and individual detail agree

The per-listing drawer uses the same stage strip, comparison rules, image
badges, blocked messages, and progress vocabulary as the individual listing
deploy page.

Why: there must not be two explanations of what the same plan will do.

## Flow at a glance

```text
Listings
  -> Generate all-listings plan
  -> Review all changes
       -> Inspect any listing in the bottom drawer
       -> Apply the reviewed plan
  -> Follow aggregate and per-listing progress
  -> Review complete or partial result
  -> Back to Listings
```

Leaving the page during apply does not stop the run. Returning to the route
reattaches to the active or most recent unseen run.

## 1. Entry point on Listings

The entry point sits in the Listings page header beside **New listing**.

| Interaction                         | What happens                                                                                                                                                 | Why it is there                                                                                                                             |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------- |
| Read **Deploy changes**             | The control is the same height and visual tier as **New listing**. Compact `+`, `-`, and `~` badges show candidate add, remove, and edit counts on one line. | Batch deploy is an important page action, but it should not create a taller second header tier or overpower the primary Listings hierarchy. |
| Hover the control                   | A summary card names the candidate listings under Add, Edit, and Remove.                                                                                     | The seller can check the likely scope without leaving the list or waiting for remote planning. Names are more actionable than counts alone. |
| Focus the control with the keyboard | The same summary card appears.                                                                                                                               | Information revealed on hover must also be available without a pointer.                                                                     |
| Activate **Deploy changes**         | Navigate to **Review all changes** and immediately start a fresh all-listings plan.                                                                          | The entry action is review, not apply. A fresh plan is required because remote state may have changed.                                      |

### Meaning of the pre-plan counts

The Listings-page counts and names come from current local listing lifecycle
and status data:

- a local draft is a candidate to add;
- a dirty deployed listing is a candidate to edit; and
- a pending-delete listing is a candidate to remove.

They are an orientation aid, not the approval boundary. Remote drift and live
state are only known after the all-listings plan completes. The hover card
therefore ends with **Open to generate a fresh plan across all listings.**

If there are no local candidates, the control remains available without count
badges so the seller can still check for remote drift.

## 2. Generating the plan

Planning may require several Printify and Etsy reads, so the review route has a
dedicated initial state rather than showing an empty review page.

| Interaction or state             | What happens                                                                                                                                                                                  | Why it is there                                                                                                    |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Enter the route                  | Show **Planning all listings...**, a progress indicator, and the explanation **Reading Printify and Etsy to work out what apply would change across this workspace. Nothing is written yet.** | The delay is expected work, not an apparent hang. The copy also reassures the seller that no mutation has started. |
| Stage planning events arrive     | The page may update a compact progress message, but it does not reveal incomplete totals as final results.                                                                                    | Partial totals are easy to mistake for the complete scope. The review should settle once the plan is complete.     |
| Select **Back** while planning   | Cancel the plan at the next safe planning boundary and return to Listings.                                                                                                                    | Planning is read-only and cancellable; there is no reason to make the seller wait for work they no longer want.    |
| Reload or revisit while planning | Reattach to the active run and rebuild state from recorded events.                                                                                                                            | A reload must not create a duplicate all-listings plan or lose progress.                                           |

If image previews must be rendered, the review may appear as soon as planning
finishes. Pending image tiles show progress, and Apply stays disabled until all
required previews are ready. This preserves the individual deploy guarantee
that the images shown during review are the images Apply will upload.

## 3. Review all changes

When planning completes, the page becomes the approval surface for the entire
run.

### Page summary

The page header reads **Review all changes** and shows when the plan was
generated. Immediately below it, a summary states the authoritative number of
affected listings and the exact Add, Edit, and Remove counts from the plan.

Why: this is the first point at which local intent and live remote state have
been reconciled. These counts, not the Listings-page preview badges, define the
run the seller is reviewing.

### Overall run stages

The aggregate stage strip is visually the same kind of control as the
individual listing step strip.

| State                   | What the stage tile shows                                                                                                | Why                                                                                                                              |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------- |
| Review                  | `0/N` and **N listings will run**.                                                                                       | The seller sees how widely each stage applies before approving the run.                                                          |
| Applying                | `X/N`, a running indicator, and **Running - {listing title}**. The title is interactive and opens that listing's drawer. | The count communicates aggregate progress; the listing title answers what is happening now and provides a direct path to detail. |
| Complete                | `N/N` and **All listings done**.                                                                                         | Completion is visible per stage, not only as one page-level success message.                                                     |
| Failed or stale listing | Successful completions remain counted. The tile exposes that the run has an exception and links to the affected listing. | Progress must not be erased by one failure, but `N/N` must not imply every listing succeeded.                                    |

There is one tile for every stage that appears in any returned plan, ordered by
the engine pipeline. The UI must not assume that every listing has the standard
five stages: lifecycle work can return a `retract` stage, and future stages
should appear without redesigning the page.

### Grouped listing rows

Affected listings are grouped as:

- **Add to Etsy**;
- **Change on Etsy**; and
- **Remove from Etsy**.

Each row contains the listing title, a short plain-language summary such as
**title, price and images**, and either its planned stage count or live progress.

| Interaction              | What happens                                                                                            | Why it is there                                                                                             |
| ------------------------ | ------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------- |
| Scan a group             | The heading includes the number of listings in that group.                                              | The seller can assess the type and scale of risk before opening individual details.                         |
| Read a row during review | The trailing value says **N stages**.                                                                   | It signals how much work the listing requires without exposing engine detail in the main list.              |
| Read a row during apply  | The trailing value changes through `0/N`, `X/N - running`, and **Done**. The active row is highlighted. | The row becomes a stable place to follow one listing while the aggregate stage strip follows the whole run. |
| Activate a row           | Open the individual listing drawer.                                                                     | Detail is available on demand without navigating away from the batch context.                               |

Listings that cannot run are never silently omitted. They appear with the
existing blocked treatment and are inspectable in the drawer. If several are
fully blocked, the implementation may group them under **Needs attention**;
this is an exception group, not a fourth change type. The Apply count includes
only listings with runnable work.

## 4. Individual listing drawer

Selecting a listing opens a bottom drawer over the review page. The page stays
in place behind a scrim, preserving the seller's position and the run's
aggregate context.

### Drawer structure

1. A fixed header shows the action category, listing title, and summary.
2. The individual step strip shows which stages will run and why.
3. The same side-by-side comparison used by individual deploy shows listing
   content and media.
4. The body scrolls independently while the header and Close action remain
   available.

Why: the seller needs enough detail to approve consequential changes, but a
full navigation for every listing would make reviewing a batch slow and would
lose their place.

### Opening and closing

| Interaction                                              | What happens                                                             | Why it is there                                                                                                                                            |
| -------------------------------------------------------- | ------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Activate a listing row                                   | Slide the drawer up and focus its heading or Close control.              | Motion communicates that this is detail layered over the batch, not a new route. Moving focus makes the modal context clear to assistive technology users. |
| Activate the current-listing title in an aggregate stage | Open the same drawer for that listing.                                   | Progress and diagnosis are connected; the seller need not search for the row manually.                                                                     |
| Activate **Close**                                       | Close the drawer and return focus to the control that opened it.         | The seller returns to the same review position and keyboard context.                                                                                       |
| Press `Escape`                                           | Close the drawer.                                                        | This is the expected keyboard behavior for temporary overlay detail.                                                                                       |
| Activate the scrim                                       | Close the drawer.                                                        | Pointer users get a quick dismissal target without implying cancellation of the plan or apply.                                                             |
| Scroll, swipe, Page Down, Home, or End in the body       | Scroll only the drawer's content. Do not move the review page behind it. | Long comparisons, especially image-heavy ones, must be fully inspectable without losing the drawer header or batch context.                                |

In production the drawer behaves as a modal dialog: background controls are
not keyboard-reachable while it is open, and focus remains within the drawer
until it closes.

### Comparison reading order

The comparison follows the buyer-facing listing order:

1. Images
2. Title
3. Description
4. Price
5. Colours
6. Tags
7. Materials

Images appear first because media order and composition strongly affect the
listing a buyer sees and are otherwise easy to miss below text changes.

Image badges use the individual deploy vocabulary:

| Badge       | Placement   | Meaning                                              | Why                                                                               |
| ----------- | ----------- | ---------------------------------------------------- | --------------------------------------------------------------------------------- |
| **Removed** | Before side | This current Etsy image will not remain after apply. | Dimming and labeling the existing image makes destructive media changes explicit. |
| **New**     | After side  | This image will be uploaded.                         | The seller can distinguish a new upload from an unchanged image at a glance.      |
| **was N**   | After side  | The image remains but moves from its previous rank.  | Order changes matter on Etsy even when the underlying image is unchanged.         |

An existing Etsy listing uses **On Etsy now** and **After apply** columns. A new
listing has one **After apply** column with **Not on Etsy yet.** Lifecycle
removal shows what is being removed and the retract stage that performs it.

During apply, opening the drawer changes the heading above the step strip from
**What apply will do** to **Live progress for this listing**. Completed stages,
the running stage, and any failure update from the same run event stream as the
aggregate view.

## 5. Applying the plan

The page footer is the authorization point.

| Interaction or state           | What happens                                                                                                      | Why it is there                                                                                                           |
| ------------------------------ | ----------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| Review is ready                | Show **Apply N listings** and the note **Apply runs exactly this plan, one listing at a time.**                   | The action names its scope, and the note states the two safety guarantees the seller is relying on.                       |
| Previews are still rendering   | Keep Apply disabled and show preview progress.                                                                    | Apply must not upload an image the seller could not review.                                                               |
| Activate **Apply N listings**  | Close any open drawer, submit the expected plan fingerprints, and start the all-listings apply run.               | Closing the drawer returns attention to run-level progress; fingerprints enforce that the approved plan is still current. |
| Apply is running               | Replace the action with a disabled **Applying...** control. Update aggregate stages and listing rows from events. | A second apply must be impossible, while progress remains continuously visible.                                           |
| Activate **Back** during apply | Return to Listings without cancelling.                                                                            | Remote writes cannot be safely cancelled at an arbitrary point. Navigation should not pretend otherwise.                  |

Apply follows the engine's continue-on-error rule. A failure in one listing is
recorded, the UI marks that listing, and the run proceeds to the next listing.
Stages that completed before the failure remain completed and recorded.

## 6. Leaving, reloading, and returning

The run belongs to the UI server, not the React component.

| Situation               | What happens                                                                                                               | Why                                                                            |
| ----------------------- | -------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Leave during planning   | Cancel the read-only plan at a safe boundary.                                                                              | Avoid unnecessary remote reads when the result is no longer wanted.            |
| Leave during apply      | Apply continues. Listings exposes **Deploying... View progress ->**.                                                       | Navigation must not put a partially applied workspace into an ambiguous state. |
| Reload the review page  | Rebuild the view from stored run events and resume the event stream from the last event id.                                | A browser refresh must not duplicate or forget a run.                          |
| Return after completion | Show the unseen result. Listings exposes **Deployed - View result ->** or **Deploy failed - view** until it has been seen. | The seller can safely leave and still receives the outcome.                    |

Only one active run may hold a listing. If another run already owns any listing
in the all-listings scope, the UI attaches to or explains the conflicting run
rather than starting competing work.

## 7. Completion and results

### Complete success

Show a success callout, keep every aggregate stage at `N/N`, mark every listing
row **Done**, and change the footer to **All planned work finished.** Statuses
are re-fetched from the server rather than guessed by the browser.

Why: completion should preserve the review record while making the overall
outcome unmistakable. Re-fetching keeps draft, deployed, live, dirty, and
deleted lifecycle states accurate.

### Partial success

Show a partial-result callout with successful and failed listing counts. Keep
successful listing and stage progress visible. Failed rows open to the exact
stage and user-facing error. Offer **Plan again** for the remaining work.

Why: continue-on-error means the truthful result is neither a generic success
nor a total failure. The seller needs to know what changed before retrying.

### Stale plan

If a listing changes after review, do not write that listing. Mark it stale,
continue according to the engine's batch rules, and require **Plan again** to
review its current state.

Why: this is the visible expression of the reviewed-plan fingerprint guard.

### Nothing to do

If the fresh all-listings plan finds no changes, show **Everything is up to
date**, hide Apply, and offer **Back to listings** and **Plan again**.

Why: an empty stage grid looks unfinished; a positive terminal state confirms
that the remote check completed successfully.

## 8. Failure behavior before apply

| Failure                                  | UI response                                                                                                                   | Why                                                                                                |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| Planning cannot read a service           | Show the user-facing error with **Try again** and **Back to listings**. Do not show stale preview counts as a completed plan. | The seller cannot approve a plan that was not built from current state.                            |
| A listing is blocked by local validation | Keep it visible, identify the blocked stage and reason, and exclude work that cannot run from the Apply count.                | The CLI and UI share the same refusal vocabulary; a blocked listing must never disappear silently. |
| A preview render fails                   | Mark the affected image or listing, keep Apply disabled for an incomplete review, and offer retry.                            | Image review is part of authorization, not decoration.                                             |
| The event stream disconnects             | Show reconnecting status, fetch the current run detail, and resume from the last event id.                                    | A transient browser connection must not be presented as a failed backend run.                      |

Errors should reuse the engine's user-facing messages. Unexpected errors use a
generic recovery message and direct the seller to server logs; raw tracebacks or
credentials never appear in the browser.

## 9. Accessibility and input behavior

- **Deploy changes**, aggregate current-listing links, listing rows, Close, and
  Apply are native buttons or links.
- The compact count badges have one accessible label, for example **2 to add,
  1 to remove, 3 to edit**; screen readers should not announce punctuation as
  the only meaning.
- The hover summary is also shown on `focus-within` and does not contain actions
  that pointer users alone can reach.
- The drawer is labeled by the listing title, traps focus while open, closes on
  `Escape`, and restores focus to its trigger.
- Progress updates expose a concise live-region message such as **Etsy media,
  2 of 4 listings complete; running Mountain sunrise tee**. Do not announce
  every low-level log line.
- Counts use tabular numerals so progress does not visually jump as it changes.
- Drawer and page scroll positions are independent.
- Motion honors `prefers-reduced-motion`; the drawer appears and disappears
  without a slide when reduced motion is requested.
- Color is never the only signal for new, moved, removed, running, blocked, or
  failed states; every state also has text or an icon.

## 10. Responsive behavior

- On a wide desktop, the drawer begins at the content edge beside the persistent
  sidebar. On narrower layouts it spans the viewport width.
- The aggregate stage strip wraps from six columns to three and then two while
  preserving engine order.
- Listing summaries wrap below titles before progress values are allowed to
  collide.
- The Listings header actions may wrap as a group, but **Deploy changes** keeps
  its single-line compact count treatment.
- The drawer height is bounded by the viewport. Its header remains visible and
  its body provides the scroll area for the complete diff.

## 11. Implementation-facing acceptance criteria

The interaction is complete when all of the following are true:

1. Activating the Listings control starts one all-listings plan without the
   browser supplying listing names.
2. The planning screen is visible for the full duration of the initial remote
   read and states that nothing is being written.
3. The authoritative review counts are derived from the completed plan.
4. Every aggregate stage reports planned total, successful count, and the
   currently running listing.
5. Every affected or blocked listing remains discoverable in the review.
6. Opening a listing shows its real stage strip and complete comparison,
   including image additions, removals, and rank changes.
7. The drawer body scrolls through the full diff while its header remains
   available.
8. Apply is disabled until the plan and all required previews are ready.
9. Apply submits expected fingerprints and never writes a stale listing plan.
10. Apply progress is sequential and survives navigation or reload.
11. A failed listing does not erase completed progress or stop later listings.
12. Success, partial success, stale, blocked, planning failure, and no-change
    outcomes each have an explicit recovery or exit action.
13. Keyboard and assistive-technology users can reveal the entry summary,
    inspect every listing, close the drawer, and understand progress.

## Out of scope

- Selecting only some listings for a batch. This feature deliberately means
  all listings.
- Reordering the engine's stage or listing execution order in the browser.
- Cancelling an apply in progress.
- Persistent run history across server restarts; that belongs to the runs
  recorder phase.
- Changing the existing individual listing plan-and-apply flow. Batch deploy
  reuses it for detail.

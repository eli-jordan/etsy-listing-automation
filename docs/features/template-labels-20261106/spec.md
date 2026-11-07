# Mockup template labels

Status: implemented, in review. Started 2026-11-06.
This specification owns the requirements under the
[documentation authority rules](../../README.md#documentation-authority). The
[interactions document](interactions.md) records the behaviour a screenshot
cannot show and where the prototype implements it.

## Outcome

A seller tags each mockup template with what its photo shows, such as
`shot:flat lay`, `model:female` or `theme:christmas`. On a listing's Images tab
they find suitable templates by adding those labels as pills in the search box,
and by typing to narrow the result by title. The Mockup Templates rail searches
the same way.

Labels are for finding templates. They never change a render, never reach Etsy
and never appear in `plan`.

## Labels

A label is free-form text. No list of allowed labels exists, and a label exists
only while a template holds it.

A new label is saved lower case, with outer spaces trimmed and repeated spaces
collapsed. It must also meet these rules:

| Rule | Limit | Message |
|---|---|---|
| Characters | Letters, numbers, spaces, hyphens and colons | Letters, numbers, spaces, hyphens and colons only |
| Length | 30 characters | Labels can be up to 30 characters |
| Colon | At most one, with text on both sides | Use one colon with text on both sides, like theme:christmas |
| Count | 10 per template | Templates hold up to 10 labels |

The 30-character limit keeps a pill usable in the 228px rail. Duplicates on one
template are dropped.

The text before a colon is the label's group. It affects only how the dropdown
lays labels out. Everywhere else a label is one string shown in full, so
`theme:christmas` and `season:christmas` cannot be mistaken for each other, and
two pills in one group still mean a template must hold both.

Renaming, merging or deleting a label across templates is out of scope. With 16
templates, editing each one is workable, and suggestions steer the seller to
labels that already exist. Existing templates are labelled by hand in the app.

## Storage

Labels are a `labels:` list at the top level of `template.yaml`, on all three
template kinds. The seller chose this over a separate file in the template's
folder, which would have avoided the hash change below.

An empty list writes no key, so `template.yaml` is unchanged for a template with
no labels. Saves use the existing text-preserving edit (ADR-0055). A template
rename needs no change, because the file moves with the folder. A template with
no `template.yaml` has no kind yet and cannot hold labels, so the Labels bar stays
hidden until its kind is set.

**Hand edits never block rendering.** The template model accepts any list of
strings. The rules above apply when the app saves a label that the template did
not already hold, so a hand-edited label that breaks them still loads, still
appears, can be removed, and does not stop other labels being saved. Every other
`template.yaml` field refuses bad values, and labels differ on purpose: a typo
in a label cannot affect a pixel, so it must not stop a listing rendering. A
`labels:` value that is not a list of strings is still a load error.

## Keeping labels out of rendering

Today `render.py` hashes the bytes of `template.yaml` (`hash_file`, in the
template load around line 647). That value feeds `scene_hash` and `_input_hash`,
for both photo-warp and prepared scenes, so a label edit would mark every scene
using the template stale and re-render every listing that holds one.

The template hash becomes the hash of those bytes with the `labels` key removed,
by the same text-preserving edit. A file with no `labels` key hashes exactly as
it does today, so nothing re-renders when this ships. Hashing raw bytes is
deliberate: it counts an edit a parser would round-trip away as a change. This
is a narrow exception to that rule, and `docs/architecture.md` must record it
under *Two hashes, doing different jobs*.

Removing the key restores the original bytes when the app wrote it. A hand
edit that leaves a comment beside the key can still change the hash once, which
costs one re-render and nothing else.

A save that changes only labels must leave these unchanged, and a test must
prove each one:

| State | Why it is at risk |
|---|---|
| Render input and scene hashes | They read the file's bytes. |
| Listing previews | They are matched against the scene hash. |
| Marigold map readiness | Preparation reads the saved template. |
| Preparation queue | `put_config` calls `reconcile_saved` and queues `cover_recalibrated` after every save. Both must queue nothing. |
| Calibration status | It is derived from the saved template. |
| `plan` output | A label edit must report no changes. |

## Saving

Labels travel in the calibrator's existing config save (`PUT
/templates/{name}/config`) with its revision check and normal debounced autosave.
The seller chose this over a dedicated endpoint, so a label edit waits for the
debounce, shares its save with any other pending edit, and quick edits land
together. No separate endpoint is added.

The Labels bar shows saved labels, not the draft. A chip appears or disappears
when the save succeeds, and the app's existing save status shows progress. If a
save fails the chips stay as they were and the error shows beside the bar. The
draft keeps the edit, so the next save carries it. A revision conflict uses
today's Reload template, which discards the draft.

The calibration revision covers the whole config, so it does change on a label
save. That is the save fence working, and nothing rendered may depend on it.

The server applies the label rules on save and refuses with a `422` naming the
rule. The client applies the same rules first, so the field can explain them
before anything is sent.

`TemplateSummary` gains `labels`. Regenerate the typed client afterwards
(ADR-0011). The calibrator's existing catalog refresh after a save updates the
rail and the suggestions.

## Search

The Mockup Templates rail and the Add media panel share one search box. It
replaces the rail's search input and the locator's. A template is listed only if
it holds every pill and its name contains the typed text, ignoring case. Plain
text searches names only.

Typing text contained in any label opens a dropdown of matching labels, which
the arrow keys and Enter turn into a pill. Text matching no label opens nothing
and stays a title search. Nothing is highlighted until the seller presses an
arrow key, so Enter can always keep text as a title search.

A label that shares no template with the current pills is marked as replacing
them, and picking it does. The seller can therefore never reach an empty list by
picking a label.

The dropdown groups labels by prefix, A to Z, with plain labels under *Other*
last. It shows no headings when no offered label has a prefix. Within a group,
labels that narrow come first, then those starting with the typed text, as a whole
or after the colon, then the highest count.

### Listing Images

The search box opens empty on all templates. An opening filter taken from the
listing's title was designed and dropped, because the seller found it annoying.
The filter is therefore always the seller's own, and a result line reads "5 of
16 templates".

Pills and text belong to the editor's view memory, beside the locator's mode, query
and open row (`useViewState`, in `sessionStorage`, keyed by listing). Nothing
reaches `listing.yaml`. They survive moving between tabs, a refresh, and leaving
and returning in the same browser tab, and they go when the tab closes. The seller
first asked for a reset on leaving the listing, then chose this once main had added
view memory, so pills behave like everything else in the locator. Switching the
panel to Files keeps the pills and clears the text, as it clears the search today.
Files keeps its plain search.

Counts and the "of N" total cover what the locator lists, which is calibrated
templates. Each row shows its labels in place of the kind line.

The listing template editor uses the same component and behaves the same way.

### Mockup Templates rail

The status and kind pills stay and apply first, so the dropdown's labels and
counts cover only what they leave. Pills and text survive switching template and
reset on leaving the page. Each row gains a line showing its labels, or "No
labels".

## Refusals

A label save is refused for the reasons in *Labels*, and for anything that
already refuses a calibration save. Nothing else blocks it: a label edit is
allowed during a deploy run or a preparation job, because it cannot change what
either is doing.

## Limits

Search matches text only, so `xmas` does not find `theme:christmas`. There is no
automatic labelling, no bulk tagging and no CLI command. Nothing guards against
hand edits racing a save beyond the existing revision check.

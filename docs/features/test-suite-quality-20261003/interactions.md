# UI interaction preservation

This companion to the [specification](spec.md) describes what must remain true
while test setup and calibration internals change. It proposes no new screen,
copy, layout or gesture. Existing listings, market-SEO, deployment and batch
interactions remain authoritative for their respective features.

## Calibration

Selecting a template, kind, photo and bundled design produces the same preview.
Editor-sized previews retain source-image coordinate meaning. Dragging moves
all corners by the same delta; corner scaling and modifier gestures retain
their current anchor and constraints. Repeated pointer moves use the box at
gesture start, so an identical move does not compound a scale. Selection,
gesture completion and callbacks still reach the selected placement.

Pure geometry tests assert concrete coordinates; component tests prove events
reach that module. A real browser proves non-identity screen/image transforms,
clipping, decoded image dimensions, full-preview/lightbox behavior and Save's
written `template.yaml`, for each distinct template kind.

Reset discards unsaved edits and restores the latest successfully saved values.
It is disabled when nothing is edited. A refetch policy is not part of this
interaction contract. Preview coalescing, newer-result precedence and keeping
the last good preview after an error remain observable promises.

## AI readiness and suggestions

A readiness request distinguishes checking from settled ready, refused or
failed. Refusal/failure keeps AI unavailable and explains why; a test must wait
for that distinct reason rather than the initial disabled state. The correct
listing identifies the request. Suggestions remain reviewable, never applied
just because generation completed. Repair failure and Try again keep their
existing visible recovery behavior.

Provider fallback order is tested through the provider/orchestrator interface.
If fallback has unique visible warning content, retain a small presentation
case for that content. Reload/replay and persisted proposal state remain real
SPA/server tests. Choosing common copy persists its ref and lead and displays
literal lead, blank line and body; no expected description is computed with
the production composer in the same assertion.

## Media, focus and forms

The parent Images tab still wires add/remove/reorder, previews, file/template
browsing and the listing-derived swatch template. MediaReel owns empty/count/
limit messages and position labels. Pure media rules own caps, eligible swatch
links and video placement. Removing duplicate parent messages does not remove
these callback/derivation witnesses.

Drawers restore focus on close; market content arriving preserves the active
title input. Mode buttons switch real content. Width or obstruction requirements
need actual layout evidence; a historical CSS class is not that evidence.
Ordinary keyboard/typing/focus scenarios use realistic user interactions.

## Save and deployment timing

No concurrent autosave patches, merged pending edits, protection from older
responses, create-once naming and rename draining a save remain covered.
Tab changes still flush relevant edits and rename changes the URL. Timer-based
tests settle clock and request independently, then assert saved data/state.

Applying sends the reviewed plan/fingerprint. Leaving a result page before its
mark-seen deadline prevents the mark request. Stream replay, reattachment,
restart recovery and cancellation remain observable HTTP/UI behavior.

## Appearance evidence

[Mockups](mockups.md) identifies comparison frames. Capture any changed runtime
surface before and after its extraction with the same synthetic fixture at
1280 × 800. Historical mockups are design context; an unchanged-current-UI
baseline governs preservation when they differ from production. Use real
pixels for geometry/appearance and DOM tests for accessible interaction.
Screenshots saved for human review are labeled artifacts, not automated
appearance assertions. The opt-in capture path keeps all five existing scenes.

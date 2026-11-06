# Mockup template labels implementation plan

Written 2026-11-06 from the [specification](spec.md) and the approved
[interactions document](interactions.md). Status: not started. This plan owns the
delivery sequence; the spec owns requirements and the interactions document owns
UI behaviour. Cite their sections rather than restating them.

The clickable source is two boards: **Find templates on a listing**
([`src/ui/design/scenes/listing-template-filter/`](../../../src/ui/design/scenes/listing-template-filter/))
and **Mockup template labels**
([`src/ui/design/scenes/template-labels/`](../../../src/ui/design/scenes/template-labels/)),
with the shared box in
[`src/ui/src/components/LabelSearch.tsx`](../../../src/ui/src/components/LabelSearch.tsx).
Keep the frames fixture-driven; copy markup and styles into production components.
Screenshots for comparison are in [`screenshots/`](screenshots/).

## Decisions

| Id | Decision |
|---|---|
| P0 | Every delegate runs on `claudeAgent` `claude-opus-5-5` with `fastMode` on, at the default medium effort, whatever the PR's difficulty. The seller ruled out Codex and Grok for this stack (2026-11-06). |
| P1 | Split: labels in the template and out of rendering; the Labels bar; the search box on the rail; the search box on the listing. The first PR is backend only, because every later PR needs `labels` from the API and the rendering guarantee is the riskiest work. |
| P2 | The Labels bar comes before search. Once it ships the seller can start tagging, and search has real data to test against. |
| P3 | No new real-shop e2e cases. Labels change nothing sent to Etsy or Printify, and the existing GitHub e2e workflow covers deploys. |
| P4 | Never use the live workspace. Tests use `tests/fixtures/workspace/`. The seller tags the 16 real templates by hand after PR 2 merges. |

## Delivery sequence

Commit the spec, interactions document, screenshots, mockup scenes and this plan
as documentation before implementation; that commit is the stack base. Record it
and each PR link here when execution starts. Each PR is based on the preceding tip.

Before that commit the seller must decide whether the real template photos in
`src/ui/design/assets/template-labels/` and `screenshots/` may go in this public
repository. The mockup frames import those thumbnails, so a "no" means swapping
placeholders in first.

| PR | Title | Difficulty | Branch | Link |
|---|---|---|---|---|
| 0 | Stack base: docs and mockups | — | `feat/mockup-template-labels` | [#190](https://github.com/eli-jordan/etsy-listing-automation/pull/190) |
| 1 | Template labels in the model, out of rendering | hard | `feat/labels-1-model` | — |
| 2 | Labels bar on the Mockup Templates workbench | standard | `feat/labels-2-bar` | — |
| 3 | Label search box on the rail | standard | `feat/labels-3-rail` | — |
| 4 | Label search box on Listing Images | standard | `feat/labels-4-listing` | — |

Size: aim under about 1,500 changed lines per PR, excluding regenerated
OpenAPI/client files and lockfiles. A PR that cannot fit splits at a seam the
orchestrator agrees, not mid-feature.

### PR 1 — Template labels in the model, out of rendering

Spec: *Labels*, *Storage*, *Keeping labels out of rendering*, *Saving* (server
half), *Refusals*.

Scope:

- `labels: list[str]` on `ColourMatrixTemplate`, `MultipleTemplate` and
  `SingleTemplate` in `core/render/config.py`, accepting any list of strings.
- `dump_template_config` omits the key when the list is empty. Otherwise every
  template gains `labels: []` in dumps, which would change every calibration
  revision and write the key into new files. Removing the last label removes the
  key from the file.
- The label rules as one pure function in `core/config/`, with the spec's messages.
  `CalibrationStore.save` tidies and checks only labels the saved template did not
  already hold, drops duplicates, and refuses with a `422` naming the rule.
- The template hash in `core/engine/stages/render.py` (`_load_template`) hashes the
  file's bytes with the `labels` key removed, using `edit_yaml_bytes`. Keep
  `hash_file` for a file with no key. When the key cannot be removed, such as a
  value shared through a YAML alias, fall back to the raw bytes. Rewrite the comment
  there, which currently states the raw-bytes rule without an exception.
- `TemplateSummary.labels` through `TemplateOverview`, and `labels` on the config
  response. Regenerate `docs/openapi.json` and the typed client.
- Record the exception in `docs/architecture.md` under *Two hashes, doing different
  jobs*. Add **Label** to `CONTEXT.md`.

Exit when:

- a test proves a template with no labels hashes byte-for-byte as before, against
  a hash computed the old way;
- a test proves adding, changing and removing labels leaves every state in the
  spec's table unchanged: `_input_hash`, `scene_hash`, preview currency, map
  readiness from `saved_inputs`, calibration status, and `plan` reporting no
  changes;
- tests prove `reconcile_saved` and `cover_recalibrated` queue no job after a
  label-only save, on a prepared Marigold template and on a positioned one;
- tests cover each rule and message, tidying, duplicates, a hand-edited invalid
  label loading and surviving an unrelated save, a non-list value failing to load,
  and labels moving with a template rename;
- a test proves saving a label keeps the seller's comments and formatting in
  `template.yaml` (ADR-0055);
- shared gates pass.

Deviations recorded while building it:

- `put_config` skips `reconcile_saved` and `cover_recalibrated` after a save that
  changed only labels. The plan expected both to find nothing to do, but a
  positioned template short of coverage, or one with stale maps and evidence in
  hand, would have queued work. `save_calibration` reports `labels_only`; a save
  with no change at all still reconciles as it always did, which keeps the
  editor's Approve, which saves an unchanged draft on purpose.
- The three preview request models take `labels`, because the client spreads a
  whole config into the preview body and they forbid unknown keys.
- The characters rule is ASCII, as in the prototype, so "letters" excludes `é`.
  Rules are checked in the prototype's order: length, characters, colon. A blank
  label takes the characters message.
- `edit_yaml` now keeps a file's missing final newline when its last key goes.
  Without it, a label added to such a file moved the hash.

### PR 2 — Labels bar on the Mockup Templates workbench

Spec: *Saving*. Interactions: *Tagging a template*, *What the production
implementation must finish*. Frames `template-labels/labelling` and
`template-labels/labelling-refused`.

Scope:

- A `LabelsBar` component above the editors in `src/ui/src/App.tsx`, on Calibrate
  and Preview, hidden until the template has a kind.
- Chips read `session.saved`, not the draft. Add and remove go through
  `session.update`, so they ride the normal autosave.
- Add label field with suggestions from the catalog's labels, Create, Enter and
  Escape, and a client copy of the rules that shows the reason in place of Create.
- Add label disabled at 10, with the message visible without hovering.
- Failure shows beside the bar. A conflict uses today's Reload template.
- A row line on the rail for labels, or "No labels". The rail's own search stays
  until PR 3.

Exit when:

- vitest covers the chip waiting for the save, quick edits landing together, each
  refusal, the cap, a failed save leaving chips unchanged, and the bar hidden with
  no kind;
- a test proves a label edit does not re-fetch or invalidate the calibrator's
  preview, and that a save held by a pending preview keeps the status visible;
- a browser test adds and removes a label against a real server, reloads, and reads
  it back from `template.yaml`;
- mockup-vs-app screenshots for both frames are in the PR;
- shared gates pass.

Deviations recorded while building it:

- A label-only save leaves the revision an editor preview names where it is, so
  the frame's request does not change and nothing re-fetches. The preview sends
  that revision's labels, and `editor_preview` accepts it while the saved document
  with those labels hashes to it. The session lists the revisions label saves moved
  through, so preparation reporting one of them is not "waiting for calibration
  status". No HTTP shape changed; only a docstring in the OpenAPI document did.
- A label-only save does not read preparation again, since it rebuilds nothing.
- The header reads "Saving…" from a label edit on, through the debounce and any
  hold behind a preview. Other edits keep today's status until their save starts.
  A failure or conflict stays on show through further edits.
- A failed save shows beside the bar only when labels are waiting to save. A
  failure of anything else stays in the header alone.
- A refused save now shows the server's sentence, not "could not save
  template.yaml".
- Suggestions show the tidied form of a label, and leave out a hand-edited label
  that would be refused on another template. Typing a label the template holds
  offers no Create. The 10-label cap counts the draft, so an edit still waiting to
  save counts.
- The field's Enter is prevented. Left to run on, it clicked the Add label button
  that focus returns to and opened the field again, which only a browser shows.

### PR 3 — Label search box on the rail

Spec: *Search*, *Mockup Templates rail*. Interactions: *One search box*, *Picking a
label*, *Mockup Templates rail*. Frames `template-labels/filtered` and
`template-labels/typing-label`.

Scope:

- Move `_LabelSearch.tsx` and its stylesheet into `src/ui/src/components/`, with
  `useId` ids and case-insensitive matching. Point the frames at the new home and
  delete the `design/components/` copy, as Marver's promotion rule says, then update
  the links in the interactions document. Archived scenes keep their `_snapshot/`.
- Replace the search input in `TemplateRail`. Status and kind apply first, and the
  box's labels and counts cover what they leave.
- Pills and text survive switching template and reset on leaving the page.

Exit when:

- vitest drives every row of the interactions document's input table, group order
  with Other last and no headings when nothing has a prefix, the replacing rule,
  and title search on top of pills;
- a browser test filters the rail with the keyboard alone, from typing `CHR` through
  Down and Enter to a pill, against a real server with labelled fixture templates;
- the keyboard and focus behaviour in G5 is checked, including the ARIA combobox
  attributes;
- mockup-vs-app screenshots for both frames are in the PR;
- shared gates pass.

Deviations recorded while building it:

- Matching ignores case everywhere, not only for the typed text. Two spellings of
  one label are offered once, as first written, and count together; a pill matches
  either spelling (`holdsLabels` in `labelRules.ts`, which callers filter with). A
  hand-edited `Theme:` sits in the `theme` group, and a label with nothing before
  its colon goes under Other.
- The prototype's box needed finishing for G5. Every close clears the highlight, so
  Enter after an outside click cannot pick a stale row. Tab closes the dropdown,
  which would otherwise stay over the rail. A pill's × returns focus to the box. The
  highlighted row scrolls into view. Down with nothing to offer highlights nothing.
  `aria-controls` names the listbox only while it exists, and the field gains
  `aria-autocomplete="list"`.
- "Starting with the typed text" also matches the text after the colon, where the
  prototype compared the whole label only, so `chr` ranks `theme:christmas` first
  within its group. The spec says so now.
- `.template-rail__search` stays in `index.css`, because the live Marigold frames
  still use it.
- The key handler split into a `keys` table for the app's lint rules, with no change
  in behaviour.
- `LabelSearch.css` uses two-class selectors for the box and pill. The bundle puts
  `index.css` after it, so `.input` and `.tag` were winning in the built app and not on
  the canvas.

### PR 4 — Label search box on Listing Images

Spec: *Search*, *Listing Images*. Interactions: *Listing Images*, *What the
production implementation must finish*. Frames `listing-template-filter/opening`,
`filtered`, `browse-labels`, `typing-label` and `narrowing-by-title`.

Scope:

- Replace the locator's template search in `MediaLocator` with the search box, and
  add the "5 of 16 templates" line. Files keeps its plain search.
- Hold pills in `MediaLocator` with `useViewState`, as a new slot beside its mode,
  query and open row, under the same `scope`. `LabelSearch` stays controlled, so the
  locator passes both values in.
- Switching to Files keeps the pills and clears the text.
- Labels, counts and the total cover calibrated templates only.
- Labels in place of the kind line in `LocatorTemplate`.
- The listing template editor shares `MediaLocator` and its `scope`, so it gets all
  of this with no separate work.
- A short section in `docs/guides/getting-started.md` on labelling and finding
  templates.

Exit when:

- vitest covers pills surviving a remount, staying separate per listing, a stored
  value from an older build being ignored, the Files rules, and counts ignoring
  uncalibrated templates;
- browser tests filter and add a colour on a listing, move to Pricing and back and
  refresh with the filter intact, and do the same in the listing template editor;
- mockup-vs-app screenshots for all five frames are in the PR;
- shared gates pass.

## Shared gates

| Gate | Exit condition |
|---|---|
| G1 | Test-first for production behaviour (`tdd` skill). Fakes for workflows; no new real-shop e2e cases (P3). |
| G2 | `uv run poe check` from the repository root in Cygwin zsh. Python and frontend keep their 85% branch floors. Do not lower gates or exclude new code. |
| G3 | `npm run test:design` from `src/ui`. UI PRs build the SPA and run the relevant `pytest -m browser` cases. Mockup frames stay fixture-driven. |
| G4 | After API shape changes regenerate `docs/openapi.json` and the typed client in the same commit. Core stays free of server/CLI imports; Import Linter passes. |
| G5 | UI PRs compare against the frames and the interactions document: keyboard, focus and save/error states. The app's stylesheets have no dark theme, so compare in light only. |
| G6 | No local e2e. After green CI run the GitHub e2e workflow (`gh workflow run e2e --ref <branch>`), one run at a time, and record its URL. Never use the live workspace (P4). |
| G7 | Update affected docs (spec, architecture, guides, `CONTEXT.md`) in the owning PR. Record deviations here. |

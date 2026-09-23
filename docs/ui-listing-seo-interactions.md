# Listing SEO AI Mode interactions

**Status:** implemented interaction design; updated for the current editor.

This document is the implementation companion to the drafting
[SEO prompt source](../seo_prompt.md). It describes what each interaction does
and why it matters, including loading, stale, invalid, and unavailable states.

The [PRD](prd.md) remains the product authority. Its AI Mode and structured
description decisions are settled here; this document records the interaction
contract they require.

## Purpose

AI Mode helps a seller draft the three SEO-sensitive parts of a listing:

- title;
- tags; and
- the opening paragraph of the description, called the **description lead**.

It is an editing aid inside Listing Details, not a separate generation
workflow. Suggestions appear next to the field they affect, the seller can
resolve each field independently, and accepted text becomes ordinary editable
listing content.

The one thing it does *not* wait to be asked for is the brief those three
suggestions are generated from. Attaching a design to a listing with an empty
brief drafts one from the artwork and requests the proposal it unblocks, so the
seller usually arrives at Listing Details to find the drawers already open
(PRD 68). Section 1a describes that chain; everything else in this document is
unchanged by it, because the brief is a generation *input*, not one of the
three reviewed outputs.

The interaction is intentionally lightweight. It should feel like opening a
small drawer attached to a field, not leaving the listing editor for an AI
workspace.

## Product invariants

1. Generation never changes a listing field by itself, with one named
   exception: the `brief`, which is a generation input rather than copy a
   shopper reads, is drafted into an *empty* brief field on design attach and
   never over text the seller wrote (section 1a).
2. A title or description lead changes only when the seller chooses a specific
   suggestion.
3. Tags change only when the seller chooses individual tags or activates
   **Accept best 13**.
4. A chosen value becomes normal, human-owned listing content. The existing
   autosave path persists it; there is no separate AI save or apply step.
5. Rejecting or closing a suggestion drawer does not undo values already added
   to normal fields.
6. Suggestions are temporary browser state, not another source of truth for
   listing copy.
7. Regeneration may replace pending suggestions, but never accepted listing
   values.
8. All three drawers live in the existing Listing Details screen and may be
   resolved in any order.

## Flow at a glance

1. The seller attaches a design. If the brief is empty, it is drafted from the
   artwork and generation starts on its own; the seller may go straight to
   step 4. Steps 2 and 3 are what a seller does when it did not, or when they
   want a different result.
2. The seller enters a brief in Listing Details and activates the AI Mode button once it is enabled.
3. The button enters a loading state while the current listing facts are sent
   for generation.
4. When generation finishes, the title, tags, and description-lead drawers
   appear automatically beside their fields.
5. The seller chooses or dismisses each set of suggestions independently.
6. Chosen values appear in their normal fields and follow existing autosave
   behavior.

There is no **View results** step, results page, modal, or global **Accept all**
action.

## 1. AI Mode entry point

The **AI Mode** control sits to the right of the Brief field, as in the [v3 review mockup](../src/etsy_listings/ui/frontend/design/scenes/listing-seo-v3/review.tsx). Its compact
button has a purple and pink sparkle and remains secondary to **Deploy changes**.

| Interaction                      | What happens                                                                                                                                                  | Why it is important                                                                                                |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Hover or focus **AI Mode** when it cannot run | Show a small card listing the saved listing, design, brief, prompt, and provider requirements, with the current readiness reason when available. | A disabled control explains what the seller can do next. |
| Hover or focus **AI Mode** when it can run | Show **Generates SEO fields using AI (title, description lead and tags)**. | The ready control needs a description of the action, not a checklist the seller has already satisfied. |
| Activate **AI Mode** | Capture the current generation inputs and begin one request for a complete proposal. | A single explicit action keeps model usage predictable and ensures all suggestions share the same listing context. |
| The listing is unsaved or a prerequisite is unavailable | Keep the control visible and disabled. | Sellers can discover AI Mode while preparing the required inputs; requests still require a saved listing and ready local tooling. |

For v1, AI Mode requires a saved listing with a selected design, a non-empty
listing brief, `prompts/seo.md`, and at least one ready provider. The brief is
editable in Listing Details. Garment-profile and other existing listing facts
are included in the submitted snapshot. The
client learns availability from the saved-listing readiness endpoint; it never
guesses from browser state. Readiness is checked again after a successful
autosave so a newly filled brief can enable the button.

## 1a. Drafting on design attach

Attaching a design is the moment a listing first has something for a model to
look at, and it is also the moment the seller is furthest from the copy they
will eventually need. So that transition — and only that transition — starts
the work by itself (PRD 68).

| Interaction | What happens | Why it is important |
| --- | --- | --- |
| Attach or change the design while the brief is empty | Draft a brief from the artwork, write it into the ordinary Brief field, and request the SEO proposal it unblocks. | The seller reaches Listing Details to review suggestions rather than to start a two-minute wait. |
| Attach or change the design while the brief has text | Do nothing at all. | A brief the seller wrote is the authority on the design; regenerating over it would lose the one input only they have. |
| Attach the design before the listing has a name | Wait. Draft as soon as naming has saved the listing. | Every request still needs a saved listing, and the natural create order puts the design first. |
| Type in the Brief field while a draft is in flight | Abandon the draft; the seller's text wins. Generation still follows once their brief is saved. | Two authors of one field is the failure to design out, not to detect afterwards. |
| The draft or the generation it started fails | Show the failure where AI Mode already shows one, and stop. **AI Mode** and **Try again** remain. | A background attempt that quietly retries spends a subscription budget nobody asked it to. |
| Leave the editor while either request runs | Abort it, exactly as **Cancel** does. Retain no brief and no proposal. | Section 7's cancellation rule is about who is left to own a result, and that does not change because the request started itself. |

The drafted brief is ordinary listing content the moment it lands: editable,
autosaved through the normal path, and carrying no badge, no pending state, and
no accept step. It is not part of the proposal, so it never goes stale and is
never cleared by resolving a drawer.

The chain arms once per attach. Changing the design again re-arms it — but only
while the brief is still empty, which after a successful draft it is not.

Brief drafting has its own prompt, `prompts/brief.md`, seeded exactly as
`prompts/seo.md` is, and runs through the same provider chain, deadline and
cancellation machinery. A workspace missing it can still use AI Mode manually;
only the automatic draft is unavailable.

## 2. Loading and automatic reveal

Immediately after activation, show an inline status message in Listing Details
and disable **AI Mode** until the request completes. The seller may continue
editing other fields while generation runs.

| State      | UI response                                                                                                     | Why it is important                                                                                  |
| ---------- | --------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| Generating | Keep **AI Mode** disabled. The sparkle twinkles and the button glows in a pulse. Under the button, **Generating for 0:00 seconds** counts up beside **Cancel**. Hovering the button shows **Generating title, description and tag recommendations for your review**. Motion is still when reduced motion is requested. | The request can take time, so the button itself shows that work is underway, and the seller can see how long it has run and stop it without the card staying open. |
| Success    | Remove the loading message. If the seller is looking at the page, the suggestion drawers slide out from under Title, Tags, and Description lead, slightly narrower than those fields, headed by the AI Mode sparkle. A proposal restored later appears in place, without the slide. | The drawers should read as coming out of the fields they belong to, and a later visit should not replay that motion. |
| Failure    | Remove the loading state and show an inline user-facing error with **Try again**. Do not change listing fields. | A model or validation failure must never look like an empty successful result.                       |
| Cancelled  | Remove the loading state and retain no proposal. Do not change listing fields.                                  | Leaving the editor, losing the connection, or pressing **Cancel** must not leave a result from an abandoned request. |

The backend tries Codex first. Only recognised provider-unavailable,
authentication/quota, or rate-limit failures fall through to Claude Code; a
malformed response receives one repair attempt from the same provider. Every
other error exposes **Try again**. The whole request, repair, and allowed
fallback share one 60-second deadline.

A short fixed delay is not a product requirement; the implementation reveals
results when the real request completes.

## 3. Title suggestions

AI Mode generates exactly three title options. They appear in a compact drawer
attached below the existing Title field, using the same body typography as tag
suggestions.

| Interaction                 | What happens                                                                                                 | Why it is important                                                                        |
| --------------------------- | ------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------ |
| Activate a title option     | Replace the Title field with that option, close the title drawer, and let normal autosave persist the field. | One click is both the decision and the action; a second accept control would be redundant. |
| Activate **Reject all**     | Close the title drawer and leave the Title field unchanged.                                                  | The seller can dismiss an unhelpful set with a clear, reversible action.                   |
| Edit the chosen title later | Treat it exactly like manually entered title text.                                                           | AI output is a draft owned by the seller, not locked generated content.                    |

There is no title **Accept** button and no default selection.

## 4. Tag suggestions

AI Mode generates exactly 20 unique, ranked tag candidates. The first 13 are
shown under **Best 13**; the remaining seven are shown under **More options**.
This ranking supports a quick default while keeping alternatives available.

| Interaction                                     | What happens                                                                               | Why it is important                                                                  |
| ----------------------------------------------- | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------ |
| Activate an unselected tag                      | Add it immediately to the normal Tags field and mark the suggestion selected.              | The seller sees the real listing state change at the point of choice.                |
| Activate a selected suggestion                  | Remove it from the normal Tags field and return the suggestion to its unselected state.    | Toggling makes comparison and correction lightweight.                                |
| Remove a selected tag from the normal chip list | Remove it from the listing and return any matching suggestion to its unselected state.     | Both representations stay synchronized; there is only one tag value.                 |
| Activate **Accept best 13**                     | Replace the normal tag list with the first 13 ranked suggestions and close the tag drawer. | This is the fast path for sellers who trust the ranking, while remaining explicit.   |
| Reach 13 selected tags                          | Disable every remaining unselected suggestion until a selected tag is removed.             | The UI prevents an invalid Etsy tag count instead of reporting it after the fact.    |
| Activate **Close**                              | Close the tag drawer. Tags already selected remain in the normal Tags field.               | Tag choices are applied individually, so closing should not silently roll them back. |

The drawer always shows the current count as **n of 13 tags selected**. Selected
state uses text or an icon as well as color. Tags retain the existing maximum
length, uniqueness, and normalization rules before they enter the listing.

## 5. Description-lead suggestions

AI Mode generates exactly three description-lead options. The lead is the
opening paragraph a shopper reads before the reusable or listing-specific body.
Its drawer is attached below the Description lead field.

| Interaction                | What happens                                                                                     | Why it is important                                                                    |
| -------------------------- | ------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------- |
| Activate a lead option     | Replace the Description lead field, close its drawer, and let normal autosave persist the field. | The seller can judge the option in its real location and continue editing immediately. |
| Activate **Reject all**    | Close the lead drawer and leave the field unchanged.                                             | Dismissing weak options must not erase existing copy.                                  |
| Edit the chosen lead later | Treat it exactly like manually entered text.                                                     | The seller remains the final author and can correct tone or factual nuance.            |

There is no description-lead **Accept** button and no default selection.

## 6. Description composition

The listing model is `etsy.description`, with a required `lead` and exactly one
optional sibling body source: reusable `ref` or inline `text`. `lead` may be
empty while the seller edits, but deployment is blocked until it is non-empty.
`text` and `ref` must never coexist.

The shared server-side composer joins a non-empty lead and resolved body with
one blank line. A lead without a body is valid. An empty lead preserves the
body as-is while editing. Printify, Etsy, snapshots, diffs, validation, and UI
preview all consume that one final concrete description; no UI handler joins it
independently.

| Interaction                                                                        | What happens                                                                    | Why it is important                                                              |
| ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Choose a common-copy item                                                          | Store its workspace-relative reference under `common-copy/` as the body source. | Reusable fit, care, and fulfillment copy stays consistent across listings.       |
| Choose **Write listing-specific body**                                             | Switch to inline-body mode with an initially blank field.                       | A listing can opt out of shared copy without creating a second competing source. |
| Switch between body modes                                                          | Replace the active body source immediately; do not retain a hidden fallback.    | Exactly one source makes the final Etsy description predictable.                 |
| A selected common-copy file is missing, malformed, or not targeted to descriptions | Show a visible Details error and block deployment.                              | Broken shared copy must be fixed before it can reach a customer-facing listing.  |

The body-source picker searches the title, summary, and reference of common
copy targeted at descriptions. **Write inline body** remains available in the
picker; choosing it reveals the inline text field below.

A common-copy file has frontmatter fields `title` and `targets`; `summary` is
optional. The initial supported target is `description`.

Legacy conversion is direct and deliberately not a compatibility reader:
`<generate>` becomes empty ordinary editable SEO values, and a legacy scalar
description becomes `description.text` unchanged with an empty `lead`. It must
not guess where an opening paragraph ends. Conversion targets are enumerated
before writing: tracked repository fixtures and the explicitly identified
desktop `try-workspace` only, never arbitrary discovered workspaces.

## 7. Proposal lifecycle and stale inputs

The pending proposal is stored only in browser local storage for one day, scoped
to its workspace and saved listing, so it can survive an accidental refresh. It
is not written to listing YAML, a generated-copy file, or the backend until the
seller chooses a value that belongs in a normal listing field.

Generation records a snapshot of the relevant inputs, including the design,
brief, garment context, and other facts supplied to the model.

| Event                                                                           | UI response                                                                                                             | Why it is important                                                                                                 |
| ------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| A relevant input changes while suggestions are pending | Keep the proposal visible, mark it stale, and disable selecting its pending values. Offer **Regenerate**. | Hiding the result would be disorienting, while accepting copy based on obsolete facts could introduce inaccuracies. |
| The editor is left or its connection closes while generation runs | Abort the request and retain no proposal. | A request without its saved-listing editor has no useful owner. |
| Activate **Regenerate**                                                         | Request a complete replacement proposal from the current inputs. Preserve all values already chosen into normal fields. | Regeneration repairs context without undoing seller decisions.                                                      |
| Resolve or dismiss one drawer                                                   | Clear only that part of the pending proposal.                                                                           | Title, tags, and lead are independent decisions.                                                                    |
| Resolve or dismiss all drawers                                                  | Remove the pending proposal from local storage.                                                                         | Temporary suggestions should not linger after they can no longer help.                                              |
| Reload with a current pending proposal                                          | Restore unresolved drawers in place.                                                                                    | A refresh should not waste a completed model request.                                                               |

Once a suggestion is chosen, it is no longer tied to the proposal and receives
no stale badge. It is ordinary listing content.

## 8. Validation, warnings, and rationale

Generated output is normalized for harmless formatting differences, then
checked against the same hard limits the listing editor and Etsy stage enforce.
This includes the title limit, tag count and length, uniqueness, and agreed
affiliation/content checks. Trademark findings are warnings, not a hard refusal.

If the first model response is invalid, repair it once with the same provider
without changing any listing field. If repair fails, use Claude only for a
recognised fall-through condition; otherwise show an inline failure and offer
**Try again**. Do not reveal a partial proposal as though it were safe to use.

Non-blocking quality warnings, returned search phrases and rationale, and
observed OCR are available through optional disclosures in the relevant drawer,
but must not add a confirmation step to choosing a value.

## 9. Persistence and autosave

Choosing a title or description lead writes directly into that normal editor
field. Choosing tags writes directly into the normal tag collection. From that
point onward, the existing editor autosave behavior owns persistence and error
recovery.

If autosave fails, keep the edited field value visible and use the editor's
normal unsaved/error treatment. Reopening or regenerating AI suggestions must
not be presented as a persistence recovery mechanism.

AI Mode is unavailable for an unnamed draft, so every accepted value has the
ordinary saved-listing autosave destination from the start.

## 10. Accessibility and input behavior

- **AI Mode**, suggestion rows, tags, **Reject all**, **Accept best 13**,
  **Close**, **Regenerate**, and **Try again** are native buttons.
- Each drawer is labeled with the field it affects.
- Tag choices expose `aria-pressed`; their disabled state is programmatically
  available when the 13-tag limit is reached.
- Loading and completion use concise polite live-region messages. Do not
  announce every suggestion individually when the drawers appear.
- Keyboard focus moves to the first useful control in the first opened drawer
  after generation, and returns to a sensible field or **AI Mode** control when
  the last drawer closes.
- Suggestion rows and subtle actions have a visible focus indicator.
- Color is never the only selected, stale, warning, disabled, or failure cue.
- Motion honors `prefers-reduced-motion`; drawers do not require an animated
  transition.

## 11. Implementation boundary

The authority documents now establish the boundaries this interaction uses:
the saved-listing readiness and request-scoped proposal endpoints are outside
`ui/runs`; provider orchestration retains no server-side proposal, job record,
or workspace output; and local storage scopes a one-day proposal by workspace
and listing. The application appends delimited JSON context and a response
schema to plain seller-editable `prompts/seo.md`; it does not support prompt
placeholders or executable prompt code.

The repository-root [seo_prompt.md](../seo_prompt.md) remains a drafting source
for the packaged default prompt. It is not read as a runtime workspace file.

## 12. Implementation-facing acceptance criteria

The interaction is complete when all of the following are true:

1. **AI Mode** is a subtle sparkle action in the upper-right of Listing Details
   for every Listing Details view; it is disabled until all prerequisites are met.
2. Activating it begins one request and shows an inline loading state without
   blocking unrelated editing.
3. Successful results appear automatically in drawers attached to Title, Tags,
   and Description lead; there is no intermediate results screen or button.
4. Title and lead each show three options. Choosing one changes its field and
   closes only its drawer; **Reject all** closes it unchanged.
5. Tags show 20 ranked options split into the recommended first 13 and seven
   alternatives.
6. Individual tag choices synchronize immediately with the normal tag chips,
   and the UI prevents selecting more than 13.
7. **Accept best 13** replaces the listing tags with the first 13 and closes
   the tag drawer; **Close** preserves individually selected tags.
8. Chosen values use the existing listing autosave path and remain freely
   editable.
9. Pending proposals survive refresh locally, become unusable when their input
   snapshot is stale, and can be regenerated without overwriting chosen values.
10. Invalid or failed generation changes no listing field and presents a clear
    retry path.
11. Description lead and exactly one body source compose deterministically for
    Etsy, and invalid common copy blocks deployment with a visible Details
    error.
12. Every action and state is operable and understandable without relying on
    pointer input or color alone.

## Out of scope

- Mobile and tablet layouts for this first version.
- Automatic generation when the editor opens, while the seller types, or on
  any listing change other than attaching a design to an empty-brief listing
  (section 1a).
- Redrafting a brief the seller has written, or a second automatic attempt after
  one fails.
- Etsy Stats, eRank, or other external performance data as generation input.
- Prompt editing inside Listing Details; prompts remain workspace/source
  configuration.
- Generating the reusable description body.
- A separate AI results page, modal, review queue, or global accept action.
- Silently replacing accepted content when the prompt, model, or listing facts
  change.

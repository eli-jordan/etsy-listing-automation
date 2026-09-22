# Listing SEO AI Mode interactions

**Status:** approved interaction design; implementation has not started.

This document is the implementation companion to the
[Listing SEO review prototype](../src/etsy_listings/ui/frontend/design/scenes/listing-seo/review.tsx)
and the current [SEO generation prompt](../seo_prompt.md). It describes what
each interaction does and why it matters. The prototype demonstrates the main
happy path in one frame; this document also specifies loading, stale, invalid,
and unavailable states that do not need separate design frames.

The [PRD](prd.md) remains the product authority. This design deliberately
changes parts of PRD decision 4 and the current listing description shape. The
documentation changes in [Implementation prerequisites](#implementation-prerequisites)
must therefore be settled before implementation.

## Purpose

AI Mode helps a seller draft the three SEO-sensitive parts of a listing:

- title;
- tags; and
- the opening paragraph of the description, called the **description lead**.

It is an editing aid inside Listing Details, not a separate generation
workflow. Suggestions appear next to the field they affect, the seller can
resolve each field independently, and accepted text becomes ordinary editable
listing content.

The interaction is intentionally lightweight. It should feel like opening a
small drawer attached to a field, not leaving the listing editor for an AI
workspace.

## Product invariants

1. Generation never changes a listing field by itself.
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

1. The seller opens **Listing Details**.
2. The seller activates the subtle **AI Mode** sparkle button.
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

The **AI Mode** control sits in the upper-right of the Listing details fieldset.
It uses the existing subtle secondary-button treatment with a sparkle icon so
it is discoverable without competing with **Deploy changes**.

| Interaction                      | What happens                                                                                                                                                  | Why it is important                                                                                                |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------ |
| Hover or focus **AI Mode**       | The control receives the same visible hover/focus treatment as other secondary actions.                                                                       | The feature remains discoverable while still reading as optional assistance.                                       |
| Activate **AI Mode**             | Capture the current generation inputs and begin one request for a complete proposal.                                                                          | A single explicit action keeps model usage predictable and ensures all suggestions share the same listing context. |
| Activate it for an unnamed draft | Generation may proceed when the other required inputs are present. Accepted copy remains local until the draft has a name and normal autosave can persist it. | Naming should not block useful drafting, but incomplete drafts must not create ambiguous workspace files.          |
| Required inputs are missing      | Disable the button. Its hover target explains which inputs are missing, such as a design or listing brief.                                                    | A specific explanation turns an unavailable feature into a fixable state.                                          |

For v1, generation requires a selected design and a non-empty listing brief.
Garment-profile and other existing listing facts are included when available as
defined by the generation stage.

## 2. Loading and automatic reveal

Immediately after activation, show an inline status message in Listing Details
and disable **AI Mode** until the request completes. The seller may continue
editing other fields while generation runs.

| State      | UI response                                                                                                     | Why it is important                                                                                  |
| ---------- | --------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------- |
| Generating | Show a compact message such as **Generating title, tag, and description suggestions…** in a polite live region. | The request can take time, so the interface must acknowledge the action without blocking the editor. |
| Success    | Remove the loading message and reveal all three field-attached drawers automatically.                           | Requiring a second click to view results adds ceremony without adding safety.                        |
| Failure    | Remove the loading state and show an inline user-facing error with **Try again**. Do not change listing fields. | A model or validation failure must never look like an empty successful result.                       |

The prototype uses a short fixed delay to demonstrate this transition. That
delay is not a product requirement; the implementation reveals results when
the real request completes.

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

The listing model separates the description into two concepts:

- `description_lead`: optional listing-specific opening copy; and
- description body: exactly one of a reusable common-copy reference or inline
  listing-specific text.

When sent to Etsy, the non-empty lead and body are joined with one blank line.
A lead without a body is valid. An empty lead preserves the body as-is.

| Interaction                                                                        | What happens                                                                    | Why it is important                                                              |
| ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| Choose a common-copy item                                                          | Store its workspace-relative reference under `common-copy/` as the body source. | Reusable fit, care, and fulfillment copy stays consistent across listings.       |
| Choose **Write listing-specific body**                                             | Switch to inline-body mode with an initially blank field.                       | A listing can opt out of shared copy without creating a second competing source. |
| Switch between body modes                                                          | Replace the active body source immediately; do not retain a hidden fallback.    | Exactly one source makes the final Etsy description predictable.                 |
| A selected common-copy file is missing, malformed, or not targeted to descriptions | Show a visible Details error and block deployment.                              | Broken shared copy must be fixed before it can reach a customer-facing listing.  |

A common-copy file has frontmatter fields `title` and `targets`; `summary` is
optional. The initial supported target is `description`.

Existing listings with one `description` value migrate that complete value to
the inline body and start with an empty lead. Migration must not guess where a
lead ends.

## 7. Proposal lifecycle and stale inputs

The pending proposal is stored only in browser local storage so it can survive
an accidental refresh. It is not written to listing YAML, a generated-copy
file, or the backend until the seller chooses a value that belongs in a normal
listing field.

Generation records a snapshot of the relevant inputs, including the design,
brief, garment context, and other facts supplied to the model.

| Event                                                                           | UI response                                                                                                             | Why it is important                                                                                                 |
| ------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| A relevant input changes while generation is running or suggestions are pending | Keep the proposal visible, mark it stale, and disable selecting its pending values. Offer **Regenerate**.               | Hiding the result would be disorienting, while accepting copy based on obsolete facts could introduce inaccuracies. |
| Activate **Regenerate**                                                         | Request a complete replacement proposal from the current inputs. Preserve all values already chosen into normal fields. | Regeneration repairs context without undoing seller decisions.                                                      |
| Resolve or dismiss one drawer                                                   | Clear only that part of the pending proposal.                                                                           | Title, tags, and lead are independent decisions.                                                                    |
| Resolve or dismiss all drawers                                                  | Remove the pending proposal from local storage.                                                                         | Temporary suggestions should not linger after they can no longer help.                                              |
| Reload with a current pending proposal                                          | Restore unresolved drawers in place.                                                                                    | A refresh should not waste a completed model request.                                                               |

Once a suggestion is chosen, it is no longer tied to the proposal and receives
no stale badge. It is ordinary listing content.

## 8. Validation, warnings, and rationale

Generated output is normalized for harmless formatting differences, then
checked against the same hard limits the listing editor and Etsy stage enforce.
This includes the title limit, tag count and length, uniqueness, banned-word
checks, and trademark screening.

If the first model response is invalid, retry generation once without changing
any listing field. If the retry is also invalid, show an inline failure and
offer **Try again**. Do not reveal a partial proposal as though it were safe to
use.

Non-blocking quality warnings remain informational. Search phrases or rationale
returned by the generator may be available through an optional disclosure in
the relevant drawer, but must not add a confirmation step to choosing a value.
The streamlined prototype omits this disclosure from its default view.

## 9. Persistence and autosave

Choosing a title or description lead writes directly into that normal editor
field. Choosing tags writes directly into the normal tag collection. From that
point onward, the existing editor autosave behavior owns persistence and error
recovery.

If autosave fails, keep the edited field value visible and use the editor's
normal unsaved/error treatment. Reopening or regenerating AI suggestions must
not be presented as a persistence recovery mechanism.

For an unnamed draft, accepted values may remain in editor state until the
listing receives a name. Naming the draft then persists the complete normal
listing document through the existing create/autosave path.

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
- The disabled **AI Mode** explanation has a hover target as approved for this
  design; it should also be exposed as an accessible description.
- Motion honors `prefers-reduced-motion`; drawers do not require an animated
  transition.

## 11. Implementation prerequisites

This companion records the approved interaction, but it cannot by itself
change settled product decisions. Before implementation:

1. Update PRD decision 4 and its AI-generation section. They currently define
   `generated.yaml` as the durable AI cache and place review at the Etsy draft.
   This design instead uses a temporary browser proposal and review inside the
   listing editor.
2. Update the PRD listing schema and the implementation plan for
   `description_lead`, the single body-source union, final description
   composition, and common-copy validation.
3. Update the implementation plan's Generate stage, applied document, and
   idempotency rules so selected human-owned fields remain stable without
   `generated.yaml` acting as their source.
4. Update [seo_prompt.md](../seo_prompt.md). It currently asks for one title,
   one description lead, and exactly 13 tags; this interaction requires three
   titles, three leads, and 20 ranked tag candidates whose first 13 are the
   recommended set.
5. Decide the backend endpoint and browser-local proposal versioning before
   implementing restore and stale detection.

These authority-document changes should be reviewed separately before the
frontend or generation stage is treated as complete.

## 12. Implementation-facing acceptance criteria

The interaction is complete when all of the following are true:

1. **AI Mode** is a subtle sparkle action in the upper-right of Listing Details
   and explains missing required inputs when unavailable.
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
- Automatic generation when the editor opens or while the seller types.
- Etsy Stats, eRank, or other external performance data as generation input.
- Prompt editing inside Listing Details; prompts remain workspace/source
  configuration.
- Generating the reusable description body.
- A separate AI results page, modal, review queue, or global accept action.
- Silently replacing accepted content when the prompt, model, or listing facts
  change.

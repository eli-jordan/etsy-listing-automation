# Multi-artwork implementation plan

**Status:** proposed implementation plan.

It implements:

- [Multi-artwork listing UI](spec.md), the product spec, which
  revises the artwork rule of the original ADR-0053;
- [Multi-artwork listing UI interactions](interactions.md),
  the UI companion; and
- the Marver mockups that document references (the **Multi-artwork** board,
  `src/ui/design/scenes/multi-artwork/`).

The plan records the implementation sequence; the spec and interactions own
the requirements. The resolver's rationale is
[ADR-0053](../../adr/0053-resolve-artwork-once-per-listing.md), which replaces
the `DesignPlacement` rule recorded as A14 in the frozen
[original plan](../../history/implementation-plan.md).

## Outcome

One pure function answers "which file does this garment colour print?", and
every reader asks it: the render stage, the Printify stage, listing validation,
the editor's previews and the AI workflow. The listing editor can then offer
light/dark base artwork and per-colour exceptions without YAML, and what it
shows is what Printify prints.

## Settled decisions

These come from the planning interview. The spec documents are the authority
for product behaviour; this table records the implementation choices they left
open, and the two places the interview amended the spec.

| Topic | Decision |
|---|---|
| Plan scope | One plan for the backend resolution rewrite and the UI port. The UI cannot promise "the file shown is the file printed" until resolution is shared, so the two are one dependency. |
| Delivery | Four stacked PRs, each an end-to-end vertical slice closing named acceptance items, each with its own success conditions. Docs (this plan, ADR-0053, spec amendments) land on the planning branch, not in a docs PR. |
| Written form | `design` is always written as a map: `{}` for no design, `{default: ref}` for one. Bare strings and `null` still load, and are normalised by the next write. |
| Removed `listing.artwork` | Rejected on load with a named message, in the style of `_reject_listing_materials`. No migration script. |
| Removed template `artwork:` | `Placement.artwork` and `SingleTemplate.artwork` are deleted. A `template.yaml` that still has the key fails to load with a message naming ADR-0053. The calibrator's pass-through of the field goes. |
| Key rules | Validators on the `Listing` model, so the CLI, engine and API refuse identically: `default` excludes both tone keys; every other key names an enabled listing colour and holds a real ref; colour keys require a reserved base key. |
| Tone classification | Garment profiles own it. An enabled colour missing from the profile's `colors:` blocks deploying and names the profile file. `new` is unchanged. The fixture profile gets tones. The old "Printify may not offer it" warning is replaced by the blocker. |
| Resolver home | A pure module, `core/config/artwork.py`. `DesignPlacement` is deleted. A failed resolution is a `Blocked`, never a `ValueError`. |
| Artwork group identity | The resolved file's **content hash**. It keys render recipes, `RenderApplied`, and Printify print areas. Reshaping the map without changing what any garment prints produces no plan; so does renaming a file. |
| AI staleness | `design_content_hash` keeps hashing the whole map, `null` slots included. Arming and the one AI image follow the representative artwork (spec: *Representative artwork*). |
| Mockup code | The mockup stays as it is. Components that already match `src/`'s style are copied into `src/` and edited there; the rest are written fresh against the real model. `fakeApi`, `ShirtPreview` and `ArtworkEditorScreen` are not copied. |
| Link dialog | `ConfirmDialog` gains an optional `children` body and a `confirmDisabled` prop. A small `ChooseBaseDialog` puts the two radio cards in that body. |
| Uncovered surfaces | Listing Images and the listings table keep today's UI and show the resolved (or representative) file. Changing garment profile follows the spec. Narrow widths are out of scope. |
| Scene resolution | A scene is resolved by the colour it depicts. A colourless `single` scene blocks in light/dark mode. Amended into the spec's *Artwork resolution* and blockers. |
| Editor previews | The server resolves each layer from the **saved** listing. The preview follows autosave rather than unsaved state. |
| Tests | Test-first (the `tdd` skill). Every acceptance item maps to named tests below. |

## ADR-0053: one listing-level artwork resolver

`core/config/artwork.py` is pure: no I/O, no workspace, no profile loading. Callers
pass the map, the colour and the profile's tones.

```python
Tone = Literal["light", "dark"]

@dataclass(frozen=True)
class Resolved:
    ref: str
    source: Literal["colour", "default", "on-light", "on-dark"]

@dataclass(frozen=True)
class SlotEmpty:          # light/dark mode, the tone's slot is null or absent
    tone: Tone

@dataclass(frozen=True)
class Unclassified:       # the colour has no tone in the garment profile
    colour: str

@dataclass(frozen=True)
class NeedsColour:        # a colourless scene in light/dark mode
    pass

@dataclass(frozen=True)
class NoDesign:
    pass

Resolution = Resolved | SlotEmpty | Unclassified | NeedsColour | NoDesign

def resolve(design: DesignMap, colour: str | None, tones: Mapping[str, Tone]) -> Resolution
def representative(design: DesignMap) -> str | None      # default, on-light, on-dark
def slot_users(design, enabled: Sequence[str], tones) -> dict[Tone, list[str]]
```

Order, per the spec: `design[colour]`, then in light/dark mode the tone's slot,
then `default`. `slot_users` counts only automatic enabled colours; it drives
the missing-slot blocker and the one-slot warning.

Readers:

| Reader | Asks |
|---|---|
| `listing_validation` | `resolve` for every enabled colour and every depicted scene colour, `slot_users` for the warning |
| `core/engine/stages/render.py` | `resolve` per layer; the layer's design identity is the resolved file's content hash |
| `core/engine/stages/printify_product.py` | `resolve` per enabled colour; colours are grouped by content hash into print areas |
| `server/api` scene preview | `resolve` per layer against the saved listing |
| `server/api/seo.py`, AI readiness, listings summary | `representative` |

Groups are keyed by content hash, so `AppliedPrintArea` becomes
`{design_hash, variant_ids}` and render recipes carry the hash rather than an
artwork key. Two differently named files with identical bytes form one group;
Printify's uploads are content-addressed already, and no print area ever
shares an image with another, which avoids an unverified Printify behaviour.

The cost is a one-off change on the first `plan` after upgrade: every render
`input_hash` and every stored print area changes shape. Renders come out
byte-identical, so the `outputs` axis is unchanged and Etsy uploads nothing.
Printify receives nothing: a print area recorded before ADR-0053 carries the same
design hash and variant ids, and its old `artwork` key is read past. The PR 1
description says so.

Rejected: rewriting `DesignPlacement` in the engine, which leaves validation and
the API with a second copy of the rule; keying groups by source key, which
turns every map reshape into a re-render and a Printify PUT.

## Standard success gates

Every PR must meet all of these. Each PR lists its own conditions on top.

- **G1. Local checks green.** `scripts/check.sh` passes: ruff, mypy, pytest
  with branch coverage, and the frontend's prettier, eslint, tsc and
  `test:coverage`. If browser tests changed, `uv run pytest -m browser` passes.
- **G2. Coverage floors held.** Python and Vitest branch coverage stay at or
  above 85%. A new module meets the floor on its own.
- **G3. PR open with green checks.** Against the previous PR in the stack (PR 1
  against `main` once the planning branch has merged). Every CI job green on
  ubuntu and windows.
- **G4. e2e green.** `uv run pytest -m e2e` locally, then
  `gh workflow run e2e --ref <branch>` green, with the run linked in the PR.
- **G5. Screens match the mockups** (PRs 2 and 3). Run the app and
  `npx marver dev` at 1280×800. For every frame the PR covers, put the mockup
  frame and the built screen **side by side as images in the PR description**.
  Fix every significant difference before review; record any agreed deviation
  with its reason.
- **G6. Behaviour matches the spec.** Walk the spec sections the PR claims and
  the interactions doc's matching Part 1 sections. Every rule is implemented
  and tested, or listed as a deliberate deviation. If the HTTP surface changed,
  regenerate `docs/openapi.json` and `src/api/schema.ts` (`npm run gen:api`).
- **G7. Size.** At most 3,000 changed lines, tests included, generated files
  excluded. Split before review, not after.
- **G8. Test-first.** Each acceptance test named below is written and seen
  failing before the code that passes it. The PR description lists the
  acceptance items it closes and the tests that prove them.

## PR sequence

```
PR 1 one resolver ──► PR 2 light/dark base ──► PR 3 a colour's own design ──► PR 4 representative artwork
```

---

### PR 1 — `refactor(artwork): one listing-level resolver`

**About 2,500 lines.** The seller sees nothing new except a clearer blocker.
Everything that prints now asks one function.

**Closes:** acceptance 1; the tone-classification part of 6.

**Scope**

- `core/config/artwork.py`: ADR-0053's resolver, `representative` and `slot_users`.
- `core/config/listing.py`:
  - `design` is `dict[str, str | None]`, loading a bare string as
    `{default: ref}` and `null` as `{}`, and always serialising as a map.
    `null` values are allowed only on `on-light` and `on-dark`.
  - The key validators from *Settled decisions*, each a field error with its
    own message.
  - `artwork:` rejected with a named message pointing at `design.<colour>`.
- `core/render/config.py`: `Placement.artwork` and `SingleTemplate.artwork` removed;
  `load_template_config` rejects the key naming ADR-0053. The calibrator's
  `MultipleEditor` and `SingleEditor` stop carrying it.
- `core/config/listing_validation.py`, through `WorkspaceFacts` (profile tones,
  template configs):
  - **block** no design chosen;
  - **block** an enabled or depicted colour unclassified, `where` naming
    `garment-profiles/<profile>.yaml` (replaces the warning);
  - **block** a needed slot empty;
  - **block** a colourless `single` scene in light/dark mode;
  - **warn** only one base slot used.
  `core/engine/stages/gates.py` turns the blocks into `Blocked`, so the render and
  Printify stages refuse instead of raising `ArtworkResolutionError`.
- `core/engine/stages/render.py` and `printify_product.py` resolve through
  `core/config/artwork.py`, keyed by content hash. `placement.py` is deleted.
- `Workspace.design_content_hash` and `seo.primary_design_image` tolerate
  `null` slots; the image comes from `representative`.
- The server's listing writes and `new` write the map form.
- Fixture: `comfort-colors-1717.yaml` gains `colors:` for black, blue-jean,
  ivory and moss. Tests that asserted the old warning change.
- `AGENTS.md`: the code layout names `core/config/artwork.py` and drops
  `placement.py`.

**Tests (written first)**

- Unit, `test_artwork.py`: every row of the spec's resolution examples; each
  `Resolution` variant; `slot_users` ignoring exceptions; `representative`
  order.
- Unit, `test_listing.py`: bare string, `null` and `{}` load; each malformed
  map is a field error; `artwork:` is refused by name; serialisation is always
  a map.
- Unit, `test_render_config.py`: a template with `artwork:` is refused naming
  ADR-0053.
- Unit, `test_listing_validation.py`: each new block and the warning, with its
  `where` text from the interactions doc §9.
- Behaviour: a listing moved from `{default: x}` to `{on-light: x, on-dark: x}`
  plans nothing; an unclassified colour and a colourless single scene are
  `Blocked`, and `--all` carries on to the next listing; a two-file listing
  sends Printify one print area per file with the right variant ids.
- Behaviour: the first plan after upgrade on an unchanged fixture re-renders
  byte-identical scenes and uploads nothing to Etsy.

**As built.** Where the implementation settled a detail differently:

| Item | Settled as | Why |
|---|---|---|
| `core/render/config.py` | A template's `artwork: null` still loads; only a non-null value is refused naming ADR-0053. The next calibrator save drops the key | The calibrator wrote `artwork: null` into every `multiple` and `single` template, so refusing the key would break every existing workspace |
| Upgrade | The first plan re-renders every listing once, byte-identical, and sends Printify nothing | `AppliedPrintArea` ignores the old `artwork` key; the stored design hash and variant ids are the ones ADR-0053 computes |
| Writes | `ListingDocuments` writes `design:` through `canonical_document`, so every writer (PATCH, create, the AI brief write, batches, `new`) converges on the map form | One written form, and one place that enforces it |
| From PR 3 | `colourSelection` drops a switched-off colour's `design` key, replacing its `artwork` handling | Leaving the key makes the save a field error (a colour key must name an enabled colour) |
| From PR 4 | AI readiness (`core/application/ai/readiness.py`) and the AI request's one image (`core/ai/listing_inputs.py`) require a representative artwork | A pair with both slots empty would otherwise crash the AI run |
| Frontend | A `DesignMap` type; `singleDesignName` and `DesignSelect` accept `null` slots; `listingDocument` sends the map as it is | The regenerated schema allows `null` slots, and the server writes the map form anyway |

**Success conditions**

- G1–G4, G6, G7, G8.
- Acceptance 1: the one-design fixture listing plans, applies and renders
  byte-identical goldens.
- No `ValueError` escapes a stage for any artwork configuration.
- `git grep -E 'ArtworkResolutionError|DesignPlacement' src` finds nothing.

---

### PR 2 — `feat(editor): light and dark base artwork`

**About 2,800 lines.** A seller can unlink, pick both base files, save a
partial pair, link back, and see the right file on every preview.

**Closes:** acceptance 2, 3, 7; the empty-slot part of 6; 5 for base slots.

**Scope**

- API: `ListingDetail.design` allows `null` slots; `gen:api`.
- `GET /api/listings/{name}/scene-preview?template=&colour=&scale=` renders a
  scene with each layer resolved from the saved listing. A layer that does not
  resolve shows the bare garment. The editor's URL carries a signature of the
  saved design map so a landed save refreshes it. `templates/{name}/design-preview`
  is retired once its two callers have moved.
- Frontend, design strip (interactions Part 2 §1–§4):
  - `ArtworkStrip` with its slot cards and per-slot recent panel, copied from
    the mockup where it matches `src/` style, otherwise rewritten; its state
    lives in `ListingEditorShell`.
  - Unlink, Link, and picking per slot, all through `update(patch)`, per the
    §3 table.
  - `ConfirmDialog` gains `children` and `confirmDisabled`; `ChooseBaseDialog`
    renders the two cards as a radio group.
  - `ArtworkPicker` for **Find a design…** per slot.
- Frontend, Variants (§5–§7): tone tags, the **no tone** tag, the prints card
  (base-slot states only), and the stage image from `scene-preview`.
- Listing Images uses `scene-preview` for every scene, multi-colour scenes
  included.
- A small display helper (`src/ui/src/pages/editor/artwork.ts`) mirrors `resolve` and
  `slot_users` for copy. The banner still renders only `detail.issues`.

**Tests (written first)**

- API: `null` slots round-trip; a malformed map is a 200 with `field_errors`;
  `scene-preview` resolves each placement of a `multiple` scene to its own
  file.
- Vitest: every §3 transition; the dialog's disabled confirm, Cancel and
  Escape; the prints card per state; the stage URL per colour.
- Browser: unlink, pick both files, reload, see both slots; link with two
  files and choose one.

**Success conditions**

- G1–G8. G5 covers frames `01`, `02`, `05`, `06`, `07`, `08`.
- Acceptance 3: `{on-light: null, on-dark: null}` survives a reload.
- Acceptance 7: the partial-pair fixture (all automatic colours dark) plans
  with the warning and no block.
- Acceptance 5 for base slots: a behaviour test compares the file each
  Listing Images layer shows with the file in that colour's Printify print
  area.

**As built.** Where the implementation settled a detail differently:

| Item | Settled as | Why |
|---|---|---|
| `design-preview` callers | Three, not two: the Variants stage, Listing Images and the deploy comparison (`ComparisonView`, used by the deploy page and the batch-deploy drawer). All three moved to `scene-preview`. The endpoint itself stayed, narrowed to the listing-template editor that `main` added while this was in review: a listing template has no artwork, so its preview design (a test design or a workspace design) is one file on every layer, with nothing to resolve | A preview keyed by one design name is a second copy of resolution for a listing, and the only honest picture for a listing template |
| Size | About 3,300 changed lines excluding generated files, over G7's 3,000; accepted as a deviation | About 290 of them are the deleted `DesignSelect` and its test |
| Narrow widths | At phone width the linked pair stacks, the Link pill centred between the cards | The existing mobile layout test forbids sideways scroll; narrow widths are otherwise still out of scope |
| Button labels | The slot cards' buttons are named "Change / Choose design for all / light / dark shirts" and "Use a different design for dark shirts", replacing "Change design" | Each names its target; tests matching "Dark" or "Light" match them exactly, since the dark card's label contains the word |
| Not here | The "Also printing their own design" names as preview links, and the row artwork chips | Both need a colour's own design, so PR 3 closes them |

---

### PR 3 — `feat(editor): a colour's own design`

**About 1,500 lines.** Any enabled colour can print its own file, in either
mode, and go back to automatic.

**Closes:** acceptance 4; 5 for colour exceptions.

**Scope**

- Variants rows: the artwork chip and **own design** tag (§5); the prints card's
  own-design actions, **Change** and **Use automatic design** (§6);
  `ArtworkPicker` per colour with the same-tone siblings hint.
- `colourSelection.ts`: turning a colour off drops its `design` key; changing
  garment profile keeps colour keys the new profile has and drops the rest.
  The old `artwork` handling there goes.
- `ChooseBaseDialog` notes "Moss keeps its own design." when exceptions exist.

**Tests (written first)**

- Vitest: pick and return to automatic, in both modes; toggle off drops the
  key; profile change keeps and drops the right keys; the dialog note.
- Behaviour: an exception that duplicates the base file plans nothing; one
  with a new file adds one print area.
- Browser: give Moss its own design, see it on the stage and in a
  multi-colour Listing Images scene, return it to automatic.

**Success conditions**

- G1–G8. G5 covers frames `03` and `04`.
- Acceptance 4 and 5 as above; the spec's *Colour-specific artwork* walked
  under G6.

**As built.** Where the implementation settled a detail differently:

| Item | Settled as | Why |
|---|---|---|
| Carried over from PR 2 | The "Also printing their own design" names preview the colour, and every sold row has its artwork chip | Both needed a colour's own design |
| Previewed colour | Lifted from `VariantsTab` into `ListingEditorShell`; `VariantsTab` takes `previewed` / `onPreview`. A strip name pressed on another tab switches to Variants | The strip sits outside the tabs and has to preview a colour too |
| Writing an own design | `update({design})` straight from `VariantsTab`, not the strip's design change | A colour's own design never arms AI or names a draft (spec: *Representative artwork*) |
| An empty draft | No chip and no card action while `design` has no reserved base key | A colour key alone is a malformed write; the base design comes first |
| Chip label | "Select different design for Moss", capitalised like the card's buttons, while row names stay lowercase | The card's "Select different design for Ivory" is the same action |
| Tests that passed first time | Both print-area behaviour tests, the acceptance-5 scene test, and the Vitest profile-change test | PR 1 keyed print areas by content hash and made `selectColours` drop a colour's key, which the profile change goes through; PR 2's `scene-preview` resolves each layer |

---

### PR 4 — `feat(ai): representative artwork`

**About 800 lines.** Only a change to the representative file starts AI work.

**Closes:** acceptance 8.

**Scope**

- `ListingSummary.design` becomes the representative ref; the listings-table
  thumbnail uses it unchanged.
- AI readiness (`useAiRun.ts`, `useAiSeoMode.ts`) requires a non-null
  representative rather than a non-empty map.
- `ListingEditorPageContent` arms the auto chain, and names an unnamed draft,
  only when `representative` changes.
- Staleness keeps comparing the whole map (Settled decisions); the identity
  helper in `aiSeoStorage.ts` handles `null` slots.

**Tests (written first)**

- Vitest: arming on a representative change; no arming on an alternate slot,
  an exception, or `{on-light: null, on-dark: null}`; draft naming.
- API: the summary thumbnail for each base shape; readiness refuses a map with
  no representative.

**Success conditions**

- G1–G4, G6–G8. G5 is not required: no screen changes.
- Acceptance 8 walked end to end in the browser layer.

**As built.** Where the implementation settled a detail differently:

| Item | Settled as | Why |
|---|---|---|
| Arming rule | Read from the map: arm, and name an unnamed draft, when `representative(next)` is non-null and differs from the current one. The strip's `onChange` no longer carries the picked file | Deciding from which control fired is what let every pick arm and no Link arm; the map says the same thing for every control. Re-picking the file already representative arms nothing |
| Readiness | `useAiRun`'s reattach and the chain's trigger, and `useAiSeoMode`'s prerequisites, ask `representative() !== null` | An empty pair holding only a colour's own design otherwise asked the server for a run it refuses |
| Pulled forward | Server readiness and `primary_design_image` (PR 1) and `designIdentity`'s `null` slots (PR 1) already held; PR 4 adds the tests that pin them | |

## Acceptance map

| Spec acceptance | PR | Proving tests |
|---|---|---|
| 1 One-artwork workflow unchanged | 1 | goldens byte-identical; one-design plan/apply behaviour test |
| 2 Switch to light/dark and pick both | 2 | browser unlink-and-pick loop |
| 3 Partial pair survives reload | 2 | API round-trip; browser reload |
| 4 A colour's own file, and back | 3 | Vitest row tests; browser Moss loop |
| 5 Preview file = Printify file | 2, 3 | behaviour test comparing scene layers with print areas |
| 6 Editor explains blockers | 1, 2 | validation tests; frame `05` and `07` comparisons |
| 7 Partial pair deploys with warning | 2 | partial-pair plan behaviour test |
| 8 Representative thumbnail and AI | 4 | arming Vitest; summary API test |

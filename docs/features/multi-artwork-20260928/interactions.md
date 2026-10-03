# Multi-artwork listing UI interactions

Status: settled interaction design (round 3 of the mockups). This document
accompanies the frames in
[`design/scenes/multi-artwork/`](../../../src/ui/design/scenes/multi-artwork/)
on the **Multi-artwork Listings** marver board.

It describes what the seller does, what the editor does in response, and why
each interaction exists. It then breaks the design down into the UI changes an
implementation has to make, with pointers into the mockup code. The product
rules come from [multi-artwork-ui.md](spec.md). Where the two
documents disagree, that specification wins.

Earlier rounds are kept on the Archive board: `multi-artwork-v1` (one design
vs light/dark as a segmented control) and `multi-artwork-v2` (five
mode-switch options; the linked pair won).

## Contents

- [Purpose](#purpose)
- [Design principles](#design-principles)
- [The frames](#the-frames)
- [Part 1: Interactions](#part-1-interactions)
  1. [Reading what a listing prints](#1-reading-what-a-listing-prints)
  2. [Changing the design for all shirts](#2-changing-the-design-for-all-shirts)
  3. [Unlinking: separate designs for light and dark shirts](#3-unlinking-separate-designs-for-light-and-dark-shirts)
  4. [Changing one base design](#4-changing-one-base-design)
  5. [Linking again: back to one design](#5-linking-again-back-to-one-design)
  6. [Giving one colour its own design](#6-giving-one-colour-its-own-design)
  7. [Returning a colour to automatic](#7-returning-a-colour-to-automatic)
  8. [Previewing a colour](#8-previewing-a-colour)
  9. [Switching colours on and off](#9-switching-colours-on-and-off)
  10. [Blockers and warnings](#10-blockers-and-warnings)
- [Part 2: UI changes and where the mockup implements them](#part-2-ui-changes-and-where-the-mockup-implements-them)
- [What the mockup fakes](#what-the-mockup-fakes)
- [Not covered by the mockups](#not-covered-by-the-mockups)

## Purpose

Today a listing has one design, chosen in the design strip above the editor
tabs. A listing whose `design:` has more than one key is read-only in the UI
([`DesignSelect.tsx`](../../../src/ui/src/pages/editor/DesignSelect.tsx)
says "edit these in listing.yaml").

The mockups let a seller do everything in the specification without editing
YAML:

1. keep the one-design workflow;
2. split a listing into a design for light shirts and a design for dark shirts;
3. give any enabled colour its own design, and take it away again;
4. see, for every colour, exactly which file it prints and why; and
5. understand what stops a deploy and how to fix it.

## Design principles

These choices shape every interaction below.

### One pair, always visible

The design strip always shows two cards, **For light shirts** and **For dark
shirts**, joined by a **Link / Unlink** button. Linked is the ordinary
one-design listing (`design.default`). Unlinked is the light/dark pair
(`design.on-light` / `design.on-dark`).

Why: v1 used a two-option segmented control above the tab strip, which put two
rows of tab-like controls on the page. The linked pair removes the extra
control entirely. It also shows the seller, before they need it, that light
and dark shirts *can* differ. The place to act is the dark-shirt card itself,
which is where the seller is already looking when a design doesn't suit a
dark shirt.

### The file shown is the file printed

Every thumbnail and preview shows the file resolved for that colour. The same
file goes into mockups and Printify. Resolution is: the colour's own design,
then the light or dark base design by the garment profile's classification,
then the one design.

Why: a preview that shows a different print from the delivered shirt is worse
than no preview (spec: *Previews*).

### Show artwork on the cloth it's for

Thumbnails sit on a tile the colour of the shirt they print on. The light slot
uses an ivory tile, the dark slot a charcoal one, and each Variants chip uses
its own colour's swatch.

Why: light ink on a light tile is invisible. "Does this ink suit this shirt?"
is the question the seller is answering whenever they look at a thumbnail.

### Explain, don't just show

The card under the preview says in words why the previewed colour prints what
it prints: "Automatic: the design for dark shirts, because bella-canvas-3001
marks black dark."

Why: resolution has three sources and depends on shared garment data. A
seller who can't see why a colour prints a file can't fix it when it's wrong.

### Incomplete is saveable; the editor says what's missing

Every edit autosaves, including a half-finished pair. Missing pieces appear in
the existing issues banner as deploy blockers. The one-slot case is only a
warning (spec: *Saving, blockers and warnings*).

## The frames

All frames are 1280 × 800 (laptop) and interactive: switching, picking and
toggling recompute the preview, the rows and the banner.

| Frame | State it shows |
| --- | --- |
| [`01-one-design`](../../../src/ui/design/scenes/multi-artwork/01-one-design.tsx) | Linked pair: one design for every shirt. |
| [`02-light-dark`](../../../src/ui/design/scenes/multi-artwork/02-light-dark.tsx) | Unlinked; both base designs chosen. |
| [`03-colour-picker`](../../../src/ui/design/scenes/multi-artwork/03-colour-picker.tsx) | Choosing a design for Moss from the full library list. |
| [`04-colour-exception`](../../../src/ui/design/scenes/multi-artwork/04-colour-exception.tsx) | Moss prints its own design. |
| [`05-missing-light`](../../../src/ui/design/scenes/multi-artwork/05-missing-light.tsx) | Partial pair; light colours need the empty slot, so deploy is blocked. |
| [`06-one-slot-used`](../../../src/ui/design/scenes/multi-artwork/06-one-slot-used.tsx) | Partial pair that can deploy; the one-slot warning. |
| [`07-unclassified`](../../../src/ui/design/scenes/multi-artwork/07-unclassified.tsx) | A colour the garment profile hasn't marked light or dark. |
| [`08-back-to-one`](../../../src/ui/design/scenes/multi-artwork/08-back-to-one.tsx) | Pressing Link: choosing which design to keep. |

---

# Part 1: Interactions

## 1. Reading what a listing prints

**What the seller sees.** Linked, the strip reads:

- left card: **For all shirts** · `take-a-hike` · "Prints on every colour you
  sell" (or "…every colour without its own design" once any colour has one);
- the **Unlink** pill;
- right card, dashed and dimmed: **For dark shirts** · `take-a-hike · linked` ·
  "Same as all shirts".

Unlinked, each card reads **For light shirts** or **For dark shirts**, its
file, and "Prints on Ivory and Natural" (the automatic colours of that tone).
If no colour needs the slot, it reads "Not used — no colour you sell needs it".

When any enabled colour has its own design, a line above the cards reads "Also
printing their own design: Moss". Each name is a link that previews that
colour.

In Variants, every enabled colour row has a small artwork chip between its
name and its light/dark tag, showing the file it resolves to on that colour's
cloth.

**Why.** The seller can answer "what will this shirt look like?" for every
colour from the strip and the list alone, without opening each colour. The
"Prints on…" line makes the base-slot calculation (spec: *Artwork
resolution*) visible, including the case where exceptions leave a slot unused.

## 2. Changing the design for all shirts

**Trigger.** Linked, press **Change ▾** on the For all shirts card.

**Response.** The inline **Recent designs for all shirts** panel opens below
the strip. It is today's panel: four recent designs as cards, the current one
highlighted, and **Find a design…**, which opens the full searchable list.
Picking a card sets `design.default` and closes the panel.

**Why.** This is today's workflow unchanged (spec acceptance 1). The Recent
panel is kept for base designs because the seller usually picks among the few
files they've just made.

**AI.** Changing the design for all shirts changes the representative
artwork, so it arms AI exactly as today's design change does.

## 3. Unlinking: separate designs for light and dark shirts

**Trigger.** Either:

- press **Unlink**, which splits the pair with the current file in both
  slots; or
- press **Use a different one ▾** on the linked dark-shirt card, which opens
  **Recent designs for dark shirts**. Picking a file splits the pair: the
  light slot keeps the old file and the dark slot takes the new one.

**Response.** Both cards become ordinary cards, and the pill becomes **Link**.
Titles change to For light shirts and For dark shirts, and each lists the
colours it prints on.

**Why.** The spec requires that switching to light/dark mode keep a valid
visual result: the current file goes into both slots. "Use a different one"
compresses the common case, where the seller is unhappy with how the design
looks on dark shirts, into one step: unlink and choose. An empty draft can
also be unlinked; both slots are then empty and `on-light: null` /
`on-dark: null` is saved (spec: *A partial light/dark pair*).

**AI.** Unlinking doesn't change the representative artwork (`on-light` now
holds the old default), so it doesn't arm AI.

## 4. Changing one base design

**Trigger.** Unlinked, press **Change ▾** (or **Choose ▾** when empty) on a
card. The same slot's panel can also be opened from the preview card's
**Choose design for light shirts** button (see §10).

**Response.** **Recent designs for light shirts** (or dark) opens; Find a
design… opens the full list, titled "Design for light shirts", with each
thumbnail on that slot's tile colour and the hint "Prints on Ivory and
Natural."

**Why.** Each base slot selects from the existing library (spec: *Base
artwork mode*). The panel names the slot so it's never ambiguous which half of
the pair is changing.

**AI.** Changing the light slot changes the representative artwork
(`default` → `on-light` → `on-dark`, first non-null) and arms AI. Changing the
dark slot doesn't arm AI while the light slot is filled.

## 5. Linking again: back to one design

**Trigger.** Unlinked, press **Link**.

**Response.**

- If both slots hold different files, a dialog asks **"Which design should
  every shirt print?"** It offers both files as cards, each on its slot's tile
  and captioned "Now the design for light shirts" or "Now the design for dark
  shirts". **Use one design** stays disabled until one is chosen, and
  **Cancel** changes nothing. When colours have their own designs, the dialog
  notes "Moss keeps its own design."
- If both slots hold the same file, or only one slot is filled, Link applies
  immediately and keeps that file.

**Why.** Leaving light/dark mode must end in exactly one chosen base file, and
nothing is committed until that choice is made (spec: *Base artwork mode*).
Asking when there's nothing to choose between would be a pointless
confirmation. Colour exceptions survive the change for colours that stay
enabled, and the dialog says so to answer the obvious worry.

**AI.** If the kept file differs from the current representative artwork
(for example the seller keeps the dark-shirt file), AI arms.

## 6. Giving one colour its own design

**Trigger.** Either:

- press a colour row's artwork chip (tooltip "Select different design"); or
- preview the colour and press **Select different design** on the card under
  the preview.

**Response.** A dialog titled **Design for Moss** opens with the full design
list only (no Recent panel). Every thumbnail sits on Moss's own swatch, and
the current file is marked **✓ Current**. The hint says who else is affected:
"Only Moss changes. Black and Navy keep the design for dark shirts." Picking a
file writes `design.moss`, closes the dialog and previews Moss.

The row then shows an **own design** tag and a green ring around its chip.
The strip's "Also printing their own design" line appears, and the preview
updates immediately.

**Why.** Per-colour exceptions are rare and deliberate, so they use the
searchable list rather than the "recent" shortcut. Showing thumbnails on the
target colour lets the seller judge the print before choosing. The
who-else-is-affected hint prevents the mistaken belief that this changes every
dark shirt.

**AI.** Colour exceptions never arm AI (spec: *Representative artwork*).

## 7. Returning a colour to automatic

**Trigger.** Preview a colour with its own design, and press **Use automatic
design** on the preview card.

**Response.** `design.<colour>` is removed immediately. The chip, the
preview and the strip's own-design line return to the base design. Before
pressing, the card has already said what automatic would mean: "Back on
automatic it would print take-a-hike-light-ink, the design for dark shirts."

**Why.** Spec: "offers a way to return to automatic resolution; doing so
removes the colour key immediately". Saying the consequence beforehand makes
the action safe without a confirmation.

## 8. Previewing a colour

**Trigger.** Press a colour row's name, as today.

**Response.** The large stage shows that colour with its resolved file. The
card under the stage has a thumbnail, a title ("Black prints
take-a-hike-light-ink") and a line explaining the source:

| Resolution | Explanation line |
| --- | --- |
| One design | "Automatic: the one design for all shirts." |
| Base slot | "Automatic: the design for dark shirts, because bella-canvas-3001 marks black dark." |
| Own design | "Its own design, for Moss only. Back on automatic it would print …" |
| Slot empty | "It's a light shirt, and no design for light shirts is chosen yet." |
| Not classified | "The bella-canvas-3001 garment profile doesn't say whether heather is a light or dark shirt. Mark it in garment-profiles/bella-canvas-3001.yaml — this listing can't decide it." |

A footnote, "Listing Images and Printify use this same file.", appears
whenever there is a file. The card's actions change with the state; see
§6, §7 and §10.

**Why.** The stage exists to judge the ink on the cloth (the existing
`VariantsTab` docstring). It must show the resolved design, never a bare
garment photo just because the listing has two base files (spec:
*Previews*).

## 9. Switching colours on and off

**Trigger.** A row's switch, or the existing **Dark** / **Light** "only these
shades" buttons.

**Response.** As today, plus:

- turning a colour off removes its own design (the row loses the tag and
  chip);
- the slot cards' "Prints on…" lines and the banner recompute. Turning off
  every light colour, for example, turns a blocker into the one-slot warning.

**Why.** Disabled colours don't keep listing-specific artwork (spec:
*Colour-specific artwork*). Recomputing live makes the relationship between
the colours sold and the slots needed obvious.

## 10. Blockers and warnings

All of these use the existing `IssuesBanner`, on the Variants tab, with the
existing "Prevents deploying" tag for blockers.

### Design for light (or dark) shirts missing — blocks deploying

Frame `05-missing-light`. "Ivory and Natural are light shirts, but no design
for light shirts is chosen", where "Artwork · For light shirts".

- The empty card gets an amber dashed border and reads "Choose the design for
  light shirts" with **Choose ▾**.
- Affected rows show an empty dashed amber chip.
- Previewing an affected colour gives the card "Ivory has nothing to print"
  with two actions: **Choose design for light shirts** (primary; opens that
  slot's Recent panel and scrolls it into view) and **Select different design
  for Ivory**.

Why: the fix is one click from wherever the seller notices the problem. The
primary action fills the slot, because that fixes every affected colour at
once.

### Only one base design in use — warning only

Frame `06-one-slot-used`. "Only the design for dark shirts is in use — no light
shirt you sell needs the design for light shirts", where "Artwork · Link the
two designs if one is all this listing needs". The unused card reads "Not used
— no colour you sell needs it". Deploy is allowed.

Why: spec acceptance 7. The warning points at unnecessary configuration and
names the remedy (Link) without requiring the seller to sell colours they
don't want to.

### Colour not marked light or dark — blocks deploying

Frame `07-unclassified`. "Heather isn't marked light or dark in the
bella-canvas-3001 garment profile", where "Fix it in
garment-profiles/bella-canvas-3001.yaml".

- The row's tone tag becomes a red **no tone** tag, with an empty chip.
- The preview card is amber-bordered, explains the problem and offers **no
  action**.

Why: tone is shared garment data. The listing can't fix it, and a colour
exception doesn't compensate (spec: *Artwork resolution*). Offering an
override would suggest otherwise.

### No design chosen — blocks deploying

"No design is chosen for this listing yet", where "Artwork". Shown for an
empty linked pair or a pair with both slots empty. This case isn't a separate
frame.

---

# Part 2: UI changes and where the mockup implements them

Paths below are relative to
`src/etsy_listings/ui/frontend/`. "Real" points at today's app code;
"Mockup" points at the frame code that implements the new design. Line numbers
are as of commit `154818d`.

## Change map

| # | UI change | Real code affected | Mockup reference |
| --- | --- | --- | --- |
| 1 | Design strip becomes the linked pair | `src/pages/editor/DesignSelect.tsx` (replace) | `design/screens/multiArtwork/ArtworkStrip.tsx` |
| 2 | Recent designs panel per slot | `DesignSelect.tsx` (the `add-panel`) | `ArtworkStrip.tsx:117-150` |
| 3 | Link / Unlink behaviour and dialog | `ListingEditorPage.tsx` (`pickDesign`) | `ArtworkEditorScreen.tsx:69-97`, `Pickers.tsx:123-191` |
| 4 | Full design list, with per-target titles and tiles | `DesignSelect.tsx` (the modal) | `Pickers.tsx:21-121` |
| 5 | Artwork chip and own-design tag in colour rows | `src/pages/editor/VariantsTab.tsx` (row markup) | `VariantsArtworkTab.tsx:138-199` |
| 6 | "What this colour prints" card | `VariantsTab.tsx` (under the stage) | `VariantsArtworkTab.tsx:201-295` |
| 7 | Stage shows the resolved design | `VariantsTab.tsx` (`templatePicture(…, design)`), `src/media.ts` (`singleDesignName`) | `VariantsArtworkTab.tsx:109-115` |
| 8 | Colour toggles drop own designs | `src/pages/editor/colourSelection.ts` | `ArtworkEditorScreen.tsx:100-101` |
| 9 | New issues in the banner | `config/listing_validation.py` (server) | `artwork.ts:63-113` |
| 10 | Resolution and slot calculation | render stage / server | `artwork.ts:36-60` |
| 11 | Styles | `src/index.css` | `design/screens/multiArtwork/multiArtwork.css` |

## 1. Design strip: the linked pair

**Real today.**
[`DesignSelect.tsx`](../../../src/ui/src/pages/editor/DesignSelect.tsx)
renders one `design-row` (thumbnail, name, file, **Change ▾**) and is
read-only for multi-key maps. It sits above the tab strip in
`ListingEditorShell` (`ListingEditorPage.tsx`, `<DesignSelect … />`).

**New.** Replace it with the linked pair.

- Component and layout:
  [`ArtworkStrip`](../../../src/ui/design/screens/multiArtwork/ArtworkStrip.tsx#L23).
  The three-column grid is `.ma-slots--linked` (`multiArtwork.css`, "the
  linked pair" section).
- Which card is which target: linked, the left card targets `default`
  (`{ kind: "one" }`); unlinked it targets `on-light`. The right card always
  targets `on-dark`.
  [`ArtworkStrip.tsx:57-59`](../../../src/ui/design/screens/multiArtwork/ArtworkStrip.tsx#L57).
- Linked wording ("For all shirts", "Prints on every colour you sell", "Same as
  all shirts"):
  [`ArtworkStrip.tsx:61-78`](../../../src/ui/design/screens/multiArtwork/ArtworkStrip.tsx#L61).
- One card:
  [`Slot`](../../../src/ui/design/screens/multiArtwork/ArtworkStrip.tsx#L155).
  It reuses `design-row`, `design-thumb`, `design-row__name` and
  `design-row__change` from today's strip. New modifiers:
  - `ma-slot--missing`: amber dashed, a slot that a colour needs but is empty;
  - `ma-slot--mirrored`: dashed and dimmed, the linked dark card;
  - `ma-slot--open`: accent border while its panel is open.
- Mirrored card copy (`· linked`, **Use a different one**):
  [`ArtworkStrip.tsx:198-206`](../../../src/ui/design/screens/multiArtwork/ArtworkStrip.tsx#L198).
- The Link / Unlink pill: a `<button aria-pressed>` with a Phosphor
  `LinkSimple` / `LinkBreak` icon and a text label.
  [`ArtworkStrip.tsx:99-115`](../../../src/ui/design/screens/multiArtwork/ArtworkStrip.tsx#L99),
  styled by `.ma-chain` / `.ma-chain--on`.
- "Also printing their own design: Moss" line, whose names preview the colour:
  [`ArtworkStrip.tsx:83-97`](../../../src/ui/design/screens/multiArtwork/ArtworkStrip.tsx#L83).
- Tile colours for thumbnails (`TILE`):
  [`artwork.ts:116-117`](../../../src/ui/design/screens/multiArtwork/artwork.ts#L117),
  applied by `.ma-tile`.

Implementation notes:

- The real thumbnail URL is `listingDesignThumbnailUrl(refName(ref))`; the
  mockup uses fixture SVG URLs.
- `DesignSelect`'s `design: Record<string, string>` prop must accept `null`
  base values (`on-light: null`), per the spec's listing document.

## 2. Recent designs panel per slot

**Real today.** `DesignSelect`'s `add-panel`: `section-label` "Recent
designs", a `template-grid` of four `template-card`s, and **Find a design…**.

**New.** The same markup, opened per target and labelled for it ("Recent
designs for dark shirts" / "for all shirts").

- [`ArtworkStrip.tsx:117-150`](../../../src/ui/design/screens/multiArtwork/ArtworkStrip.tsx#L117).
  `RECENT = 4` matches today's constant.
- Which slot is open is held by the screen, not the strip, so the preview
  card's **Choose design for light shirts** can open it:
  [`ArtworkEditorScreen.tsx:58`](../../../src/ui/design/screens/multiArtwork/ArtworkEditorScreen.tsx#L58)
  and
  [`ArtworkEditorScreen.tsx:153-156`](../../../src/ui/design/screens/multiArtwork/ArtworkEditorScreen.tsx#L153).
  In the app, that state belongs in `ListingEditorShell`.

## 3. Link / Unlink behaviour

All writes go through the existing `update(patch)` from `useAutosave`.

| Action | Mockup | `design` before → after |
| --- | --- | --- |
| Unlink | [`unlink()` L78](../../../src/ui/design/screens/multiArtwork/ArtworkEditorScreen.tsx#L78) | `{default: A}` → `{on-light: A, on-dark: A}`; colour keys kept |
| Pick for dark while linked | [`pick()` L83-97](../../../src/ui/design/screens/multiArtwork/ArtworkEditorScreen.tsx#L83) | `{default: A}` → `{on-light: A, on-dark: B}` |
| Pick for one slot | same | sets `on-light` or `on-dark` |
| Link, one distinct file | [`link()` L69-76](../../../src/ui/design/screens/multiArtwork/ArtworkEditorScreen.tsx#L69) | `{on-light: A, on-dark: A or null}` → `{default: A}` |
| Link, two files | `link()` opens `BackToOneDialog` | → `{default: <chosen>}` on **Use one design**; nothing on Cancel |

The dialog is
[`BackToOneDialog`](../../../src/ui/design/screens/multiArtwork/Pickers.tsx#L123).
It reuses `modal-root`, `modal-dialog confirm-dialog`, `confirm-dialog__title`,
`confirm-dialog__actions` and `template-card` / `template-card--active` for the
two radio cards. The disabled confirm is at
[`Pickers.tsx:182`](../../../src/ui/design/screens/multiArtwork/Pickers.tsx#L182).
It can't be `ConfirmDialog` as-is, because it needs a choice in its body.

Implementation notes:

- AI arming (see §2–§5 in Part 1) belongs in `ListingEditorPageContent`,
  where `pickDesign` arms it today. Arm only when the representative artwork
  (`default` → `on-light` → `on-dark`, first non-null) changes.
- `pickDesign`'s naming of an unnamed draft should fire for the
  representative artwork only.

## 4. Full design list

**Real today.** `DesignSelect`'s "Find a design" modal: `modal-dialog`,
search `input`, `modal-design-row` rows.

**New.**
[`ArtworkPicker`](../../../src/ui/design/screens/multiArtwork/Pickers.tsx#L21)
is shared by all targets:

- title, hint and tile per target (`Design for Moss` / `Design for dark
  shirts` / `Design for all shirts`):
  [`Pickers.tsx:37-68`](../../../src/ui/design/screens/multiArtwork/Pickers.tsx#L37);
- the "Only Moss changes. Black and Navy keep…" hint lists the automatic
  siblings of the same tone;
- **✓ Current** on the resolved file:
  [`Pickers.tsx:91`](../../../src/ui/design/screens/multiArtwork/Pickers.tsx#L91);
- a search field with a Phosphor `MagnifyingGlass` icon (`.ma-search`).

Base slots reach it through **Find a design…**; colour exceptions open it
directly (no Recent panel).

## 5. Colour rows: artwork chip and own-design tag

**Real today.**
[`VariantsTab.tsx`](../../../src/ui/src/pages/editor/VariantsTab.tsx)
row: `color-row` → preview button (swatch, name) → tone `tag` → `switch`.

**New.**
[`ColourRow`](../../../src/ui/design/screens/multiArtwork/VariantsArtworkTab.tsx#L138)
adds:

- the **own design** tag (`tag tag-accent-2 ma-own-tag`) inside the preview
  button:
  [`L162`](../../../src/ui/design/screens/multiArtwork/VariantsArtworkTab.tsx#L162);
- the artwork chip, a `<button>` labelled "Select different design for
  <colour>" that opens the colour's picker. Its background is the colour's
  swatch.
  [`L164-181`](../../../src/ui/design/screens/multiArtwork/VariantsArtworkTab.tsx#L164).
  Modifiers: `ma-chip--own` (green ring), `ma-chip--empty` (amber dashed).
  Only enabled rows have a chip.
- **no tone** (`tag tag-dirty`) in place of the tone tag for an unclassified
  colour:
  [`L185`](../../../src/ui/design/screens/multiArtwork/VariantsArtworkTab.tsx#L185).

Everything else in the tab is unchanged. `VariantsArtworkTab` is a fork of the
real tab with fixture props, and keeps its garment select, sizes, shade
buttons, stage and hint.

## 6. "What this colour prints" card

New; sits between the stage and the existing hint.

- [`PrintsCard`](../../../src/ui/design/screens/multiArtwork/VariantsArtworkTab.tsx#L201).
- Copy per resolution (the table in Part 1 §8):
  [`L223-248`](../../../src/ui/design/screens/multiArtwork/VariantsArtworkTab.tsx#L223).
- Actions per state:
  [`L266-291`](../../../src/ui/design/screens/multiArtwork/VariantsArtworkTab.tsx#L266):
  - own design → **Change** + **Use automatic design**;
  - slot empty → **Choose design for light shirts** (primary) + **Select
    different design for Ivory**;
  - otherwise → **Select different design**;
  - unclassified → none, and the card takes `ma-prints--blocked`.
- Buttons use `btn-like btn-sm` in the body face (`.ma-btn`), the same override
  `.add-panel .btn-like` already applies.
- The Printify footnote shows only when a file resolves:
  [`L263`](../../../src/ui/design/screens/multiArtwork/VariantsArtworkTab.tsx#L263).

## 7. Stage shows the resolved design

**Real today.** `templatePicture(template, shown, design)` where
`design = singleDesignName(detail.design)`. That is `null` for a multi-key
map, so today the stage falls back to a bare garment photo.

**New.** Pass the colour's resolved file:
`resolvedDesign(resolve(colour, base))`.
[`VariantsArtworkTab.tsx:109-115`](../../../src/ui/design/screens/multiArtwork/VariantsArtworkTab.tsx#L109).
The mockup draws the garment with
[`ShirtPreview`](../../../src/ui/design/screens/multiArtwork/ShirtPreview.tsx#L6);
the app keeps the real preview template image.

## 8. Colour toggles drop own designs

The mockup's `setEnabled` clears `own` for any colour switched off:
[`ArtworkEditorScreen.tsx:100-101`](../../../src/ui/design/screens/multiArtwork/ArtworkEditorScreen.tsx#L100).
In the app, that belongs in
[`colourSelection.ts`](../../../src/ui/src/pages/editor/colourSelection.ts)
(`selectColours` / `selectGarmentProfile`), next to the other colour-keyed
fields it already moves.

## 9. New issues

The mockup restates the server's rules so the frames stay interactive:
[`artworkIssues`](../../../src/ui/design/screens/multiArtwork/artwork.ts#L63).
In the app these come from the server's listing validation; the banner just
renders `detail.issues`.

| Issue | Severity | Mockup lines | `where` text |
| --- | --- | --- | --- |
| No design chosen | block | [`L67-76`](../../../src/ui/design/screens/multiArtwork/artwork.ts#L67) | Artwork |
| Colour not classified | block | [`L78-85`](../../../src/ui/design/screens/multiArtwork/artwork.ts#L78) | Fix it in garment-profiles/<profile>.yaml |
| Needed slot empty | block | [`L87-101`](../../../src/ui/design/screens/multiArtwork/artwork.ts#L87) | Artwork · For light shirts |
| Only one slot used | warn | [`L102-111`](../../../src/ui/design/screens/multiArtwork/artwork.ts#L102) | Artwork · Link the two designs if one is all this listing needs |

All use `tab: "variants"`, so the existing tab badge counts them.

## 10. Resolution and the slot calculation

- [`resolve`](../../../src/ui/design/screens/multiArtwork/artwork.ts#L36):
  own design, then light or dark slot by tone, then the one design, or
  "unclassified".
- [`slotUsers`](../../../src/ui/design/screens/multiArtwork/artwork.ts#L57):
  the enabled, automatic colours of a tone. This drives the "Prints on…"
  lines, the missing-slot blocker and the one-slot warning. Only automatic
  colours count (spec: *Artwork resolution*).

The frontend needs a small helper like this for display. The server remains
the authority for what deploys.

## 11. Styles

All new classes are prefixed `ma-` in
[`multiArtwork.css`](../../../src/ui/design/screens/multiArtwork/multiArtwork.css)
and use the existing tokens (`--space-*`, `--radius-*`, `--color-accent*`,
`--color-warning`). Sections: design strip, tiles, Variants rows, preview card,
library picker, back-to-one dialog, recent panel and linked pair. When moving
them into `src/index.css`, rename them to fit the surrounding `design-*` /
`color-row*` families.

## What the mockup fakes

- **Fake API.**
  [`fakeApi.ts`](../../../src/ui/design/screens/multiArtwork/fakeApi.ts)
  answers `/api/workspace` and `/api/runs`, so the real `AppShell` and
  `EditorHead` / `DeployControl` render. It is not part of the design.
- **Validation.** `artworkIssues` stands in for the server.
- **Artwork and garments.** SVG artwork in `design/assets/multi-artwork/` and
  the drawn `ShirtPreview` stand in for design-library PNGs and the preview
  template photo.
- **Autosave.** Edits change local state only; the page head always reads
  "Saved 2 mins ago".
- **Tabs.** Only Variants has content.

## Not covered by the mockups

- Listing Images previews showing each colour's resolved design, including
  scenes with several colours (spec: *Previews*).
- The listings-table thumbnail from the representative artwork.
- Changing garment profile while colours have their own designs.
- Narrow widths: the frames target laptop only.

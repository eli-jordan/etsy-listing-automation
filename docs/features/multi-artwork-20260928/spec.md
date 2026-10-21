# Multi-artwork listing UI

**Status:** approved product specification; not implemented. This document
extends [ADR-0053](../../adr/0053-resolve-artwork-once-per-listing.md). The exact visual design
and the implementation plan are deliberately deferred.

## Outcome

A seller can configure every artwork file a listing needs without editing
`listing.yaml`. The ordinary case remains one design file for every shirt. A
listing can instead carry separate artwork for light and dark shirts, and any
enabled colour can use its own file as an explicit exception.

The file resolved for a colour is the truth everywhere: it appears in listing
previews and Etsy mockups and is the file sent to Printify. Mockup templates no
longer choose artwork independently, because a product image that shows a
different print from the delivered shirt is not a useful exception.

## Scope

This change covers artwork selection in the listing editor, including switching
between one base artwork and a light/dark pair, selecting a different artwork
for one colour, previewing the result, and explaining incomplete configuration.

It does not add design upload or import. Every picker uses files already in the
workspace design library. It does not add garment-profile editing: colour tone
classification remains shared garment data, maintained in the garment profile.
It does not add multi-artwork questions to the `new` command. Exact control
placement, responsive layout and visual treatment belong to the later UI design.

## The listing document

`design` is the listing's complete artwork map. There is no separate mode field
and no separate `artwork` object.

Three keys are reserved for base artwork:

- `default` means that one file applies to every colour without an exception.
- `on-light` and `on-dark` mean that the base file follows the garment tone.
  The keys name the shirt the artwork is for, not the visible ink colour.

`default` is mutually exclusive with `on-light` and `on-dark`. Either tone key
may be absent or `null` while a light/dark listing is being edited. Reserved
base values are therefore a workspace-rooted design ref or `null`; colour-key
values are always real refs. Every other key must exactly name an enabled
listing colour and overrides the base for that colour.

Every non-empty map has a base: `default`, `on-light`, or `on-dark`. A map made
only of colour keys is malformed rather than an alternative all-custom mode.
An absent field, `null`, and an empty object all mean that no design has been
selected. Their canonical written form is deliberately left to the later
implementation plan.

### No design yet

This is saveable but cannot be deployed:

```yaml
design: null
```

### One base artwork

Every enabled colour uses the same file:

```yaml
design:
  default: designs/take-a-hike.png
```

### One base artwork with a colour exception

Moss uses its explicit file in mockups and on Printify. Every other enabled
colour uses the base file:

```yaml
design:
  default: designs/take-a-hike.png
  moss: designs/take-a-hike-moss-special.png
```

### Light and dark base artwork

The files are named for the shirt they print on. The artwork for a light shirt
will commonly use dark ink, and vice versa:

```yaml
design:
  on-light: designs/take-a-hike-dark-ink.png
  on-dark: designs/take-a-hike-light-ink.png
```

Given a garment profile that classifies ivory as `light` and black and moss as
`dark`, ivory uses `on-light`; black and moss use `on-dark`.

### Light and dark artwork with a colour exception

Moss ignores the base artwork selected by its `dark` classification and uses
its explicit file. Ivory and black continue to resolve automatically:

```yaml
design:
  on-light: designs/take-a-hike-dark-ink.png
  on-dark: designs/take-a-hike-light-ink.png
  moss: designs/take-a-hike-moss-special.png
```

### A partial light/dark pair

The editor saves each choice as it is made, so a light/dark object may be
incomplete. Even the mode with no files selected survives a reload:

```yaml
design:
  on-light: null
  on-dark: null
```

After one selection it may read:

```yaml
design:
  on-dark: designs/take-a-hike-light-ink.png
```

This can deploy when every enabled colour resolves without `on-light`: for
example, all automatic colours are dark. It cannot deploy while an enabled,
automatic light colour needs the missing file.

A direct exception is considered before deciding which base slots are needed:

```yaml
design:
  on-dark: designs/take-a-hike-light-ink.png
  ivory: designs/take-a-hike-ivory-special.png
```

If ivory is the only enabled light colour, this document does not need
`on-light` to deploy. The editor still warns that light/dark mode is only using
one of its base slots and may be more configuration than the listing needs.

## Artwork resolution

For each enabled colour, the listing resolves one file in this order:

1. The direct file in `design[colour]`, when present.
2. In light/dark mode, `on-light` or `on-dark` according to the garment
   profile's classification of that colour.
3. In single mode, `default`.

Only automatic colours count when deciding whether a light/dark base slot is
used. A direct colour exception removes that colour from the base-slot
calculation.

Garment colour classification remains mandatory. A listing-level file
exception does not compensate for missing shared garment data. The editor names
the garment profile that must be corrected rather than offering a listing-local
tone classification.

There is no template or placement artwork override. A colour resolves to the
same file in every mockup scene and on Printify.

A mockup scene is resolved by the garment colour it depicts: the media entry's
colour for a `colour-matrix` template, each placement's colour for a `multiple`
template, and the template's own `colour` for a `single` template. A depicted
colour follows the same order as an enabled one. A `single` template that names
no colour prints `default` in single mode and cannot be resolved in light/dark
mode; the tool does not guess which base file a photograph shows.

## Listing editor interactions

### Base artwork mode

The design area above the editor tabs offers an explicit choice between one
artwork and different artwork for light and dark shirts. User-facing labels say
"for light shirts" and "for dark shirts"; they do not expose `on-light` and
`on-dark` as unexplained technical terms.

Switching an existing single-artwork listing to light/dark mode puts its current
file in both slots. This preserves a valid visual result while the seller picks
the alternate file. An empty draft may enter light/dark mode before either file
is chosen; its two `null` reserved keys record that mode through autosave.

Switching from light/dark mode to one artwork asks which available base file to
keep as `default`. The change is not committed until that choice is made.
Direct per-colour keys survive the mode change for colours that remain enabled.

Each base slot selects from the existing design library. The later UI design
will decide the exact replace and clear interactions; the product rule is only
that a partial pair remains saveable and that leaving light/dark mode produces
one chosen base artwork.

### Colour-specific artwork

Each enabled colour row in Variants offers an action such as **Select different
design**. Picking a file adds that colour directly to `design`. The row then
makes the exception visible and offers a way to return to automatic resolution;
doing so removes the colour key immediately.

Disabled colours do not retain listing-specific artwork. Turning a colour off
continues to remove its key from `design`. Changing garment profile preserves
colour keys that exist in the new profile and removes the rest, matching the
treatment of other colour-specific listing data.

The exact row control, picker presentation and confirmation treatment are UI
design questions, not decisions in this specification.

## Previews

Every listing preview shows the artwork actually resolved for the depicted
colour. This includes the large Variants preview and every generated scene in
Listing Images, including scenes containing several garment colours. A direct
colour exception updates those previews as soon as it is selected; returning
to automatic resolution restores the applicable base artwork.

The UI must not fall back to a bare garment photo merely because `design` has
two base files. The purpose of the preview is to judge the resolved design, not
just the template geometry.

## Saving, blockers and warnings

Incomplete configuration is saveable. Malformed configuration is not.

The following are incomplete states that autosave normally but block
deployment:

- no base design has been selected;
- an enabled colour is not classified `light` or `dark` in the garment profile;
- an enabled automatic colour needs a light/dark base slot that has not been
  filled;
- in light/dark mode, the listing's media uses a `single` mockup template that
  does not name the garment colour it depicts, so no file can be resolved for
  it; or
- a selected artwork file fails the listing's ordinary file, alpha or
  resolution requirements.

The editor shows a non-blocking warning when light/dark mode is enabled but
fewer than two base slots are used after direct colour exceptions are applied.
Deployment remains valid: the warning exists to point out unnecessary
configuration, not to require the seller to enable colours they do not sell.

Combining `default` with either tone key, using a non-reserved key that is not
an enabled colour, or providing colour keys without any reserved base key
remains a rejected write with a field error. These are malformed rather than
incomplete.

## Representative artwork

Places that need one image to represent the whole listing use the first
non-null file in this order: `default`, `on-light`, `on-dark`. Colour keys are
never promoted to representative artwork. With no available reserved base file,
there is no representative image.

This rule supplies the listings-table thumbnail and the one image sent to the
brief and SEO workflow. Changing the current representative artwork has the
same AI arming behaviour as today's design change. Changing the alternate base
file or a direct colour exception does not arm AI, because those files express
print treatment rather than a new listing concept.

## Acceptance behaviour

The product change is complete when a seller can perform all of the following
without editing listing YAML:

1. Keep the existing one-artwork workflow unchanged from the seller's
   perspective.
2. Switch a listing to light/dark mode and select both base files.
3. Save and reopen a partial light/dark selection without losing its mode.
4. Assign any existing design-library file to an enabled colour, in either base
   mode, and return that colour to automatic resolution.
5. See the resolved file in every listing preview and receive the same file in
   the Printify product configuration.
6. Understand from the editor why a missing tone classification or missing
   used base slot blocks deployment.
7. Deploy a partial pair when every enabled colour resolves, while seeing the
   warning that only one base slot is used.
8. See a representative thumbnail and run AI from the preferred available base
   artwork without alternate or per-colour changes starting unintended AI work.

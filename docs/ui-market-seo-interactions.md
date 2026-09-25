# Market-informed SEO interactions

**Status:** design agreed; not yet implemented. The build order is in
[market-seo-implementation-plan.md](market-seo-implementation-plan.md).

This document is the UI companion to [Market-informed SEO](market-seo.md). That
spec decides what the chain does. This one describes what the seller sees while
the chain runs, and afterwards: the elements, their states, interactions and
animations, and why each is shaped the way it is.

The mockup is a Marver scene. Run `npx marver dev` in
`src/etsy_listings/ui/frontend` and open the **Market-informed SEO** board.

| Frame | Shows |
|---|---|
| [`researching`](../src/etsy_listings/ui/frontend/design/scenes/market-seo/researching.tsx) | Brief done, market research running, panel loading |
| [`suggesting`](../src/etsy_listings/ui/frontend/design/scenes/market-seo/suggesting.tsx) | Market research done, suggestions being written, panel filled |
| [`ready`](../src/etsy_listings/ui/frontend/design/scenes/market-seo/ready.tsx) | Suggestions ready, drawers open, first listing expanded |
| [`states`](../src/etsy_listings/ui/frontend/design/scenes/market-seo/states.tsx) | Every indicator state with its hover card pinned open, plus the panel's Phrases, empty and failed states |

The mockup code lives in `src/etsy_listings/ui/frontend/design/screens/marketSeo/`:

- [`AiWorkflowIndicator.tsx`](../src/etsy_listings/ui/frontend/design/screens/marketSeo/AiWorkflowIndicator.tsx): the page-head indicator.
- [`MarketListingsPanel.tsx`](../src/etsy_listings/ui/frontend/design/screens/marketSeo/MarketListingsPanel.tsx): the right-hand panel.
- [`MarketSeoScreen.tsx`](../src/etsy_listings/ui/frontend/design/screens/marketSeo/MarketSeoScreen.tsx): the editor around them, mirroring the real `ListingEditorPage` and `DetailsTab` markup.
- [`marketSeo.css`](../src/etsy_listings/ui/frontend/design/screens/marketSeo/marketSeo.css): all new styles.
- Fixture data is in [`scenes/market-seo/_fixtures.ts`](../src/etsy_listings/ui/frontend/design/scenes/market-seo/_fixtures.ts).

Nothing in `src/` may import from `design/`. Port the markup and styles into
the app; don't reference the mockup files.

## Contents

1. [Workflow indicator](#1-workflow-indicator)
2. [Top listings panel](#2-top-listings-panel)
3. [Layout](#3-layout)
4. [Shared visual language](#4-shared-visual-language)
5. [Where the data comes from](#5-where-the-data-comes-from)
6. [Settled details](#6-settled-details)

---

## 1. Workflow indicator

### What it replaces

Before it, `AiActivityIndicator` (deleted in PR 7)
showed a `dv-spinner` plus *Generating brief…* or *Generating SEO…* beside
*Saved a moment ago* in the page head. `ListingEditorPage` passed it in through
the `activity` prop.

The new indicator goes in the same slot and keeps that component's reasoning.
The page head reads the same on every tab, and the seller who attached a design
is usually on Variants, far from the Brief field. What changes is that the
chain is now three stages long and can take over a minute
([market-seo.md › Failures](market-seo.md#failures)). A single spinner can't say
which stage is slow, which one failed, or that one was skipped.

The chain now runs as a server-side AI run
([market-seo.md › AI runs](market-seo.md#ai-runs)). The indicator draws the
latest `step` event for each node. It works the same after a reload, because
the editor reattaches to the run and the events replay.

In the mockup it sits straight after `page-head__meta`
([`MarketSeoScreen.tsx:87-88`](../src/etsy_listings/ui/frontend/design/screens/marketSeo/MarketSeoScreen.tsx#L87)):

```tsx
<span className="page-head__meta">Saved a moment ago</span>
{steps && <AiWorkflowIndicator steps={steps} />}
```

### Anatomy

Three circular nodes joined by short connectors, then a one-line text label.

| Node | Icon (Phosphor, `bold`) | Label while active | Spec step(s) |
|---|---|---|---|
| Brief | `NotePencil` | Drafting brief… | 1. Brief (PRD 68) |
| Market research | `MagnifyingGlass` | Researching the market… | 2. Query extraction and 3. Market search |
| SEO suggestions | `Sparkle` | Writing suggestions… | 4. Proposal |

Query extraction and market search share one node. For the seller both steps
are "finding out what the market says", and nothing they could do differs
between them. The node's hover-card detail line can tell them apart (see
[States](#states)).

Step metadata is in `STEPS`
([`AiWorkflowIndicator.tsx:8-27`](../src/etsy_listings/ui/frontend/design/screens/marketSeo/AiWorkflowIndicator.tsx#L8)).
The markup
([`AiWorkflowIndicator.tsx:60-96`](../src/etsy_listings/ui/frontend/design/screens/marketSeo/AiWorkflowIndicator.tsx#L60)):

```tsx
<div className="aiflow" role="status" aria-live="polite" aria-label={`AI Mode: ${line.text}`}>
  <ol className="aiflow__nodes">
    <li className="aiflow__step">
      {index > 0 && <span className={linkDone ? "aiflow__link aiflow__link--done" : "aiflow__link"} aria-hidden="true" />}
      <span className={`aiflow__node aiflow__node--${step.state}`} tabIndex={0}
            aria-describedby={tipId} aria-label={`${meta.name}: ${STATE_WORD[step.state]}`}>
        {meta.icon}
        <Badge state={step.state} />
        <span className="aiflow__tip" id={tipId} role="tooltip">…</span>
      </span>
    </li>
    …
  </ol>
  <span className={`aiflow__label aiflow__label--${line.tone}`}>{line.text}</span>
</div>
```

**Why a text label as well as the nodes.** Icons alone make the seller hover to
learn anything. The label means the chain reads at a glance, and it keeps the
old indicator's wording style (*Drafting brief…*). It comes from `summary()`
([`AiWorkflowIndicator.tsx:39-45`](../src/etsy_listings/ui/frontend/design/screens/marketSeo/AiWorkflowIndicator.tsx#L39)):
a failed step wins, then the active step's label, otherwise *Suggestions ready*.

**Why small and quiet.** It shares a line with the title, status tag and
autosave meta, and must not read as a notification bar. The nodes are 20px with
11px icons, the connectors are 10px × 1px, and finished steps are a pale tint
rather than a solid fill. Only the running node carries colour and motion.

```css
/* marketSeo.css:45-62 */
.aiflow__node {
  position: relative;
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  border: 1px solid var(--color-divider);
  border-radius: 50%;
  background: transparent;
  color: color-mix(in srgb, var(--color-text) 35%, transparent);
  cursor: default;
  transition: background 200ms ease-out, border-color 200ms ease-out, color 200ms ease-out;
}

.aiflow__node > svg { width: 11px; height: 11px; }
```

### States

Each step is a `WorkflowStep { id, state, detail? }`
([`AiWorkflowIndicator.tsx:4-6`](../src/etsy_listings/ui/frontend/design/screens/marketSeo/AiWorkflowIndicator.tsx#L4)),
with `state` one of `pending | active | done | skipped | warning | failed`. The
`states` frame shows every combination. The fixture sets are `steps.*` in
[`_fixtures.ts:101-137`](../src/etsy_listings/ui/frontend/design/scenes/market-seo/_fixtures.ts#L101).

| State | Look | Badge | CSS |
|---|---|---|---|
| `pending` | Grey outline, grey icon; dashed connector into it | none | base `.aiflow__node` |
| `active` | Purple→pink gradient fill, purple border, ink icon, **pulsing glow** | none | `.aiflow__node--active` (L69) |
| `done` | Pale purple tint, ink icon; solid connector out of it | none | `.aiflow__node--done` (L91) |
| `skipped` | **Greyed out**, dashed outline, faint icon | grey `SkipForward` | `.aiflow__node--skipped` (L100), `.aiflow__badge--skipped` (L135) |
| `warning` | As `done` | amber `Warning` | `.aiflow__badge--warning` (L140) |
| `failed` | Red outline and icon; label turns red | red `X` | `.aiflow__node--failed` (L105), `.aiflow__badge--failed` (L145) |

`done` has no badge on purpose. A tick on every finished step was noise; the
tint and the solid connector already say it. Badges are kept for the states
that need a second look.

A connector is solid once the step before it is `done`, `skipped` or `warning`,
meaning the chain moved past it
([`AiWorkflowIndicator.tsx:68-72`](../src/etsy_listings/ui/frontend/design/screens/marketSeo/AiWorkflowIndicator.tsx#L68)).

```css
/* marketSeo.css:34-43 */
.aiflow__link {
  width: 10px;
  height: 1px;
  margin: 0 2px;
  background: repeating-linear-gradient(90deg, var(--color-divider) 0 2px, transparent 2px 4px);
}
.aiflow__link--done {
  background: color-mix(in srgb, var(--seo-purple) 45%, transparent);
}
```

#### Scenarios

| Scenario | Brief | Market research | SEO suggestions | Label |
|---|---|---|---|---|
| PRD 68 auto chain: a design picked while the brief was empty, then the first save with a name, design and garment profile | active → done | pending → active → done | pending → active → done | Drafting brief… → Researching the market… → Writing suggestions… → Suggestions ready |
| Auto chain, but the seller wrote a brief before it fired | **skipped** | active → done | active → done | starts at Researching the market… |
| **AI Mode clicked** (it requires a brief, so always) | **skipped** | active → done | active → done | starts at Researching the market… |
| No comparable listings, even with filters relaxed | done / skipped | **warning** | active → done | Writing suggestions… |
| Query extraction or Etsy search failed | done / skipped | **failed** | pending, detail *Not started* | Market research failed |

**Skipped brief.** A brief is only drafted into an empty field, and AI Mode
can only be clicked once there is a brief, so a run started from the button
always skips that step. The node still shows, greyed out with
a skip badge, rather than disappearing. That keeps the chain the same shape
every run, and it says outright that the seller's brief was used as written.
The hover card says *Skipped* with the detail *You wrote the brief, so it was
kept*.

```css
/* marketSeo.css:98-104, 135-138 */
/* Didn't run this time (the seller's own brief was kept): greyed and dashed,
   with a skip badge, so it still shows its place in the chain. */
.aiflow__node--skipped {
  border-style: dashed;
  color: color-mix(in srgb, var(--color-text) 30%, transparent);
}
.aiflow__badge--skipped {
  background: var(--color-neutral-500);
  color: #fff;
}
```

**Warning versus failed.** These follow the spec. *No comparable listings* is
the one case that goes ahead without market data, so the chain continues past
an amber badge. A failed extraction or Etsy search fails the proposal, so the
chain stops at a red node and the SEO node never starts.

**Done.** Once every node is `done` or `skipped`, *Suggestions ready* stays
for 4 seconds, then fades out over 300ms. The indicator then renders nothing,
which is the ordinary case, as it is today. Under `prefers-reduced-motion` it
disappears without the fade. `warning` and `failed` chains don't fade: they
stay until the next run or until the editor is left. The fade isn't in the
mockup, which shows the resting state.

A clean finish is only news to an editor that watched the run go. When the
editor reattaches to a run that had already finished cleanly (on a return or
a reload), the indicator renders nothing, as it was left, rather than showing
*Suggestions ready* on every visit to the listing. A reattached `warning` or
`failed` run shows again, since it still needs a look. A cancelled run, with
every node back to `pending`, renders nothing.

**Detail lines.** Every state can carry a `detail` string for the hover card.
Those in the fixtures:

- Brief: *Reading take-a-hike.png*, *Drafted from take-a-hike.png*, *You wrote the brief, so it was kept*.
- Market research:
  - *Searching Etsy for 3 phrases…*
  - *20 listings scored, from 58 found*
  - *No comparable listings found, even with filters relaxed*
  - *Etsy market search failed: \<reason\>*, using the spec's exact error prefix.
- SEO suggestions: *Writing for 0:14*, *Writing from the design and brief alone*, *3 titles, 20 tags, 3 leads to review*.

During query extraction, use a detail such as *Choosing Etsy searches from the
brief*. It is the one sub-step the node doesn't show on its own.

### Animation: the active glow

The active node pulses with a scaled-down copy of the AI Mode button's own
`seo-ai-mode-pulse` (`src/index.css:4863`). The app's pulse spreads 8px with a
26px blur, which swamped a 20px node, so the indicator gets its own keyframes
at about a third of that size:

```css
/* marketSeo.css:69-89 */
.aiflow__node--active {
  border-color: color-mix(in srgb, var(--seo-purple) 70%, transparent);
  background: linear-gradient(115deg, #f5efff, #fff0f7);
  color: var(--seo-ink);
  animation: aiflow-glow 1.5s ease-in-out infinite;
}

/* AI Mode's own pulse, scaled down to a 20px node. */
@keyframes aiflow-glow {
  0%, 100% {
    box-shadow:
      0 0 0 0 color-mix(in srgb, var(--seo-purple) 24%, transparent),
      0 0 4px 0 color-mix(in srgb, var(--seo-pink) 30%, transparent);
  }
  50% {
    box-shadow:
      0 0 0 3px color-mix(in srgb, var(--seo-purple) 18%, transparent),
      0 0 10px 2px color-mix(in srgb, var(--seo-pink) 45%, transparent);
  }
}
```

It runs at 1.5s, the same period as the AI Mode button, so while both are busy
they breathe together.

**Reduced motion: slow the pulse down, don't remove it.** Under
`prefers-reduced-motion: reduce` the period goes to 3s
([`marketSeo.css:110-116`](../src/etsy_listings/ui/frontend/design/screens/marketSeo/marketSeo.css#L110)).
This follows the lesson in the old `AiActivityIndicator`'s comment: a spinner that
stopped on a Windows machine with animations off read as a hang. Here the
motion *is* the information, so it is softened rather than removed.

```css
@media (prefers-reduced-motion: reduce) {
  .aiflow__node--active { animation-duration: 3s; }
}
```

Nodes change colour between states with a 200ms ease-out transition on
background, border and colour.

### Interaction: hover cards

Each node is focusable (`tabIndex={0}`). Its hover card appears on `:hover` and
on `:focus-visible`, so keyboard users get it too. The card is linked to the
node with `aria-describedby` and has `role="tooltip"`. It is built the same way
as AI Mode's own tip: 250px, a purple-tinted border, `--shadow-md`.

The card has three parts:

- **Head:** the step name and a state word from `STATE_WORD`
  ([L29](../src/etsy_listings/ui/frontend/design/screens/marketSeo/AiWorkflowIndicator.tsx#L29)),
  coloured by state.
- **About:** a sentence on what the step does, the same every run.
- **Detail:** this run's specifics, below a divider, in tabular numbers.

```css
/* marketSeo.css:166-198 */
.aiflow__tip {
  position: absolute;
  z-index: 20;
  top: calc(100% + 10px);
  left: -6px;                 /* left-aligned: centring clipped at the head's left edge */
  width: 250px;
  …
  opacity: 0;
  visibility: hidden;
  transform: translateY(-4px);
  transition: opacity 120ms ease-out, transform 120ms ease-out, visibility 120ms ease-out;
  pointer-events: none;
}
.aiflow__node:hover .aiflow__tip,
.aiflow__node:focus-visible .aiflow__tip,
.aiflow__node--tip-open .aiflow__tip {
  opacity: 1;
  visibility: visible;
  transform: translateY(0);
}
```

The card fades in and drops 4px over 120ms. `--tip-open` and the `openTip` prop
exist only so the canvas can pin cards open. Don't port them.

The node uses `cursor: default`, not `pointer`, because it has no click action.

### Accessibility

- The container is `role="status"` with `aria-live="polite"`. Its `aria-label`
  is *AI Mode: \<label\>*, so screen readers hear one sentence per change and
  not every node.
- Each node's `aria-label` is *\<Step\>: \<state word\>*, for example
  *Brief: Skipped*.

---

## 2. Top listings panel

### Why it's there

The spec asks for "the related listings with their thumbnail, title, a link to
Etsy, and their metrics and score", read from the snapshot so it survives a
reload ([market-seo.md › UI](market-seo.md#ui)). It is read-only in this
version.

The panel has a second job: it shows the seller *why* the suggestions read as
they do. Market data is now the main driver of wording, so the listings and
phrases the model saw sit beside the drawers the seller is choosing from.

Markup root
([`MarketListingsPanel.tsx:171-237`](../src/etsy_listings/ui/frontend/design/screens/marketSeo/MarketListingsPanel.tsx#L171)):

```tsx
<aside className="mkt-panel" aria-label="Top listings on Etsy">
  <header className="mkt-head">
    <h2 className="mkt-head__title">Top listings on Etsy</h2>
    <span className="mkt-head__meta">20 scored from 58 found · searched just now</span>
  </header>
  <Queries queries={…} />
  <div className="mkt-switch" role="tablist" aria-label="Market view">…</div>
  {view === "listings" ? <Listings … /> : <Phrases … />}
</aside>
```

```css
/* marketSeo.css:254-264 */
.mkt-panel {
  position: sticky;
  top: var(--space-4);
  display: grid;
  gap: var(--space-2);
  padding: var(--space-3);
  border: 1px solid var(--color-divider);
  border-radius: var(--radius-sm);
  background: var(--color-neutral-100);
  font-size: 12px;
}
```

It is **sticky**, so it stays in view as the seller scrolls down to Tags and
Lead, where the comparison matters most.

### Header and searches

- **Title:** *Top listings on Etsy*, in the heading font.
- **Meta line:** *\<scored\> scored from \<found\> found · searched \<relative
  time\>*, in tabular numbers. It shows how big the sample was and how fresh it
  is, because the snapshot outlives the session.
- **Searches line**
  ([`Queries`, L63-75](../src/etsy_listings/ui/frontend/design/screens/marketSeo/MarketListingsPanel.tsx#L63)):
  *🔍 Searched Etsy for "a", "b" and "c"*. These are the three queries AI Mode
  wrote from the brief.

```tsx
<p className={searching ? "mkt-queries mkt-queries--searching" : "mkt-queries"}>
  <span className="mkt-queries__label"><MagnifyingGlass weight="bold" /> {searching ? "Searching Etsy for" : "Searched Etsy for"}</span>{" "}
  {queries.map((q, i) => (
    <span key={q}>
      {i > 0 && (i === queries.length - 1 ? " and " : ", ")}
      <span className="mkt-query">“{q}”</span>
    </span>
  ))}
</p>
```

**Why a sentence and not chips.** The first version showed the queries as
purple pills. A reviewer read them as tags, which is fair, since the tags in an
expanded row are also pills. The queries now read as a plain sentence with a
verb, so they can't be taken for tags or controls. They stay in the panel
because they explain why these listings, and not others, came back.
Extraction isn't cached, so they change from run to run.

### Listings view (default)

Top-level structure
([`Listings`, L120-144](../src/etsy_listings/ui/frontend/design/screens/marketSeo/MarketListingsPanel.tsx#L120)):

- A group label, **Examples shown to AI Mode**, over the top 8 (`EXAMPLES = 8`).
- A dashed **Show \<n\> more scored listings** button, where n is scored − 8.
- Clicking the button replaces itself with **Also scored** and listings 9 to
  20. It is one-way; there is no collapse.

**Why two groups.** The spec sends the top 8 to the model verbatim, but uses all
20 for the phrase list. Labelling the split tells the seller which listings the
model actually read, and keeps the default panel short.

#### Listing row

([`ListingRow`, L77-118](../src/etsy_listings/ui/frontend/design/screens/marketSeo/MarketListingsPanel.tsx#L77))

```tsx
<li className={open ? "mkt-row mkt-row--open" : "mkt-row"}>
  <button className="mkt-row__main" type="button" aria-expanded={open} onClick={onToggle}>
    <span className="mkt-row__rank">{item.rank}</span>
    <TeeThumb {...item.thumb} />
    <span className="mkt-row__text">
      <span className="mkt-row__title">{item.title}</span>
      <span className="mkt-row__shop">
        {item.ownShop ? <span className="mkt-own"><Storefront weight="bold" /> Your shop</span> : item.shop}
        <span aria-hidden="true">·</span>
        <Star weight="fill" className="mkt-star" /> {item.shopRating.toFixed(1)}
      </span>
      <span className="mkt-row__metrics">
        <span title="Reviews on this listing"><Star weight="bold" /> {compact(item.reviews)}</span>
        <span title="Favourites per day"><Heart weight="bold" /> {item.favouritesPerDay.toFixed(1)}/d</span>
        <span title="Views per day"><Eye weight="bold" /> {item.viewsPerDay}/d</span>
      </span>
    </span>
    <span className="mkt-score" title={`Market score ${item.score} of 100`}>
      <span className="mkt-score__value">{item.score}</span>
      <span className="mkt-score__bar"><span style={{ width: `${item.score}%` }} /></span>
    </span>
    <CaretDown weight="bold" className="mkt-row__caret" />
  </button>
  {open && <div className="mkt-row__detail">…lead, tags, Open on Etsy…</div>}
</li>
```

The row is a five-column grid: rank, 40px thumbnail, text, score, caret.

```css
/* marketSeo.css:371-395 */
.mkt-row__main {
  display: grid;
  grid-template-columns: 14px 40px minmax(0, 1fr) 34px 10px;
  gap: 8px;
  align-items: center;
  padding: 7px 4px;
  border-radius: 6px;
  cursor: pointer;
  …
}
.mkt-row__main:hover { background: color-mix(in srgb, var(--seo-purple) 6%, var(--color-neutral-100)); }
.mkt-row__main:focus-visible { outline: 2px solid var(--seo-purple); outline-offset: -2px; }
```

The row's contents:

- **Title** is clamped to one line, and to three when the row is open
  (`.mkt-row__title`, L417-429). Etsy titles are long and keyword-stuffed, and
  one line is enough to recognise a listing.
- **Shop line:** the shop name and its star rating.
- **Your shop** replaces the shop name with a green pill (`.mkt-own`, L463)
  when the listing is ours. The spec deliberately keeps our own listings in the
  results, so the seller should be able to spot them.
- **Metrics:** listing reviews, favourites per day and views per day. These are
  the three highest-weighted per-listing signals in the scoring table, and each
  has a `title` explaining it.
- **Score:** 0–100, in the AI ink colour, over a 3px purple→pink bar.

```css
/* marketSeo.css:484-498 */
.mkt-score__bar {
  display: block;
  width: 100%;
  height: 3px;
  border-radius: 3px;
  background: color-mix(in srgb, var(--seo-purple) 14%, transparent);
  overflow: hidden;
}
.mkt-score__bar > span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: linear-gradient(90deg, var(--seo-purple), var(--seo-pink));
}
```

#### Expanding a row

Clicking a row toggles it. **Only one row is open at a time**, tracked as
`open: number | null` in `Listings`. The caret turns 180° over 150ms
(`.mkt-row__caret`, L500-509). The detail block (`.mkt-row__detail`, L511) is
indented to line up with the thumbnail. It shows:

- the listing's **description lead** in quotes;
- **all its tags** as small neutral chips (`.mkt-tag`); and
- **Open on Etsy ↗**, which opens `https://www.etsy.com/listing/<id>` in a new
  tab (`target="_blank" rel="noreferrer"`).

These are exactly the verbatim fields the model gets for the top 8, so the
seller can see what the suggestions were modelled on. Each part hides when its
data is empty, as it is for rows 9–20 in the fixtures. The `ready` frame opens
the first row to show this.

### Phrases view

A two-option segmented switch, **Listings | Phrases**, sits under the searches
line. The mockup draws it as `.mkt-switch` (L321-350). **The implementation
reuses the app's existing `.seg` control** and its keyboard behaviour,
instead of porting `.mkt-switch`, so the app has one segmented control.

([`Phrases`, L146-165](../src/etsy_listings/ui/frontend/design/screens/marketSeo/MarketListingsPanel.tsx#L146))

```tsx
<p className="mkt-group">Tags the top listings share, strongest first</p>
<ol className="mkt-phrases">
  <li className="mkt-phrase">
    <span className="mkt-phrase__text">
      {p.used && <Check weight="bold" className="mkt-phrase__used" aria-label="In your suggestions" />}
      {p.phrase}
    </span>
    <span className="mkt-phrase__count">{p.listings} listings</span>
    <span className="mkt-score__bar"><span style={{ width: `${p.score * 100}%` }} /></span>
  </li>
</ol>
<p className="mkt-foot">Ticked phrases made it into the current suggestions.</p>
```

This is the spec's ranked phrase list
([market-seo.md › What the proposal sees](market-seo.md#what-the-proposal-sees)):
each phrase with the number of listings using it and its 0–1 phrase score,
drawn with the same bar as the listing score. A purple tick marks phrases that
appear in the current suggestions: the phrase is one of the suggested tags,
or a suggested title or lead contains it (case-insensitive). The browser works
this out from the pending proposal. With no pending proposal there are no
ticks, and the footnote is hidden. All 40 phrases from the spec are listed. The tab turns "the market" into the words
the seller is choosing between, and shows how much of the market's vocabulary
AI Mode picked up.

### Panel states

| State | When | Shows | Frame |
|---|---|---|---|
| none | No snapshot yet and no run | Nothing: the panel isn't rendered, and the fields keep their current width | — |
| `loading` | The market node is active, including on a re-run over an existing snapshot | *Searching Etsy for …* (queries pulsing, filled by the `queries` event) and five shimmering skeleton rows | `researching` |
| `ready` | A `market` event, or a snapshot loaded on mount | Everything above | `suggesting`, `ready`, `states` |
| `empty` | The market node ended in `warning` | Searches line and a neutral note: *No comparable listings found. Etsy returned nothing for these searches, even without the age filter. The suggestions were written from the design and brief alone.* | `states` |
| `failed` | The market node ended in `failed` | A note with a red heading: *Etsy market search failed*, the reason, then *Nothing changed. Run AI Mode again to retry.* A failed run doesn't replace the snapshot, so a reload shows the previous results again | `states` |

The `PanelState` union is at
[`MarketListingsPanel.tsx:31-35`](../src/etsy_listings/ui/frontend/design/screens/marketSeo/MarketListingsPanel.tsx#L31).
The empty and failed notes share `.mkt-note` (L618-643).

The loading state is designed around the queries. They exist before any
listing does, so showing them straight away turns a blank wait into *here is
what we're looking for*.

### Panel animations

Both run only under `prefers-reduced-motion: no-preference`. They are
decoration: the page-head glow already says work is happening.

**Query pulse** while searching: each query's text fades between normal text
colour and the AI ink over 1.4s.

```css
/* marketSeo.css:309-319 */
@media (prefers-reduced-motion: no-preference) {
  .mkt-queries--searching .mkt-query { animation: mkt-breathe 1.4s ease-in-out infinite; }
}
@keyframes mkt-breathe { 50% { color: var(--seo-ink); } }
```

**Skeleton shimmer:** a neutral bar with a faint purple highlight sweeping
across it every 1.6s.

```css
/* marketSeo.css:654-686 */
.mkt-skel {
  background: linear-gradient(90deg, var(--color-neutral-200), color-mix(in srgb, var(--seo-purple) 10%, var(--color-neutral-200)), var(--color-neutral-200));
  background-size: 200% 100%;
}
@media (prefers-reduced-motion: no-preference) {
  .mkt-skel { animation: mkt-shimmer 1.6s linear infinite; }
}
@keyframes mkt-shimmer {
  from { background-position: 200% 0; }
  to { background-position: -200% 0; }
}
```

### Hover and focus summary

Every clickable part has `cursor: pointer` and a hover state:

| Target | Hover | Focus |
|---|---|---|
| Listing row | 6% purple wash | 2px purple inset outline |
| Listings/Phrases option | Text goes from muted to full | inherited button focus |
| Show more | Dashed border and text turn purple | inherited button focus |
| Open on Etsy | Underline | inherited link focus |

---

## 3. Layout

The Listing Details tab becomes two columns: the existing fieldset on the left
and the panel on the right
([`MarketSeoScreen.tsx:111-192`](../src/etsy_listings/ui/frontend/design/screens/marketSeo/MarketSeoScreen.tsx#L111)).

```tsx
<div className="mkt-layout">
  <div className="details-tab">
    <fieldset className="seo-details-fieldset">…Brief, Title, Tags, Lead, Section, Materials…</fieldset>
  </div>
  <MarketListingsPanel {...panel} />
</div>
```

```css
/* marketSeo.css:239-250 */
.mkt-layout {
  display: grid;
  grid-template-columns: minmax(0, 760px) 300px;
  gap: var(--space-6);
  align-items: start;
}
@media (max-width: 1100px) {
  .mkt-layout { grid-template-columns: minmax(0, 1fr); }
}
```

**Why the right side, at 300px.** The panel is reference material for fields
the seller is editing, so it sits beside them rather than in another tab. On a
1280px laptop, with the 240px sidebar and page padding, the fields keep about
640px, which is enough for the 140-character title input and the suggestion
drawers. Below 1100px the panel stacks under the fields.

The panel belongs to the Listing Details tab only. Variants and Listing Images
don't change.

The fields column in `MarketSeoScreen` is a straight copy of the current
`DetailsTab`, including the real `AiChoiceDrawer` and `AiTagsDrawer`. Nothing
in it is new, apart from sharing the row with the panel.

---

## 4. Shared visual language

- **The AI purple family** marks everything the AI chain produced or is doing:
  `--seo-purple #7655c9`, `--seo-pink #dc5e9a`, and ink `#593baf` for text. The
  app declares all three once, on `:root` in `src/index.css` (PR 7). Before
  that they were declared again on each AI selector (`.seo-suggestion`,
  `.seo-brief-row`, `.seo-ai-mode-anchor`), and the ink was a literal
  `#593baf`. The mockup still declares them on `.aiflow, .mkt-panel`
  ([`marketSeo.css:4-9`](../src/etsy_listings/ui/frontend/design/screens/marketSeo/marketSeo.css#L4)).
- **Neutral for data, purple for AI.** Listing tags, the Your shop pill and the
  notes use the app's neutral and accent tokens. Purple is kept for scores, the
  AI-chain nodes and interaction affordances, so it keeps its meaning.
- **Numbers** use `font-variant-numeric: tabular-nums` everywhere, so values
  don't jitter as they update.
- **Icons:** `@phosphor-icons/react`, which the implementation moves from
  `devDependencies` to `dependencies`. The mockup uses these icons:
  `NotePencil`, `MagnifyingGlass`, `Sparkle`, `SkipForward`, `Warning`, `X`,
  `Star`, `Heart`, `Eye`, `Storefront`, `CaretDown`, `ArrowSquareOut`, `Check`,
  `WarningCircle`.
- **Thumbnails** in the mockup are SVG stand-ins (`TeeThumb`). The real panel
  shows the listing's first image (its 170px URL) at 40×40, with
  `object-fit: cover` and the same 6px radius. If the image fails to load, a
  neutral tile is shown instead.

---

## 5. Where the data comes from

Everything the UI shows comes from the AI run and the snapshot described in
[market-seo.md › AI runs](market-seo.md#ai-runs).

| UI | Source |
|---|---|
| Indicator nodes, label, hover-card detail | The latest `step` event for each node |
| *Generating for X seconds* and Cancel | The run's start time; Cancel sends `DELETE /api/ai/runs/{id}` |
| Brief field filling in | The `brief` event, when `written` is true. The editor sets the field without autosaving it again |
| Panel `loading` and its searches sentence | `step market active` and the `queries` event |
| Panel `ready` / `empty` | The `market` event, or `GET /api/listings/{name}/market` on mount |
| Panel `failed` | `step market failed` and its detail |
| Suggestion drawers | The `proposal` event, stored in `aiSeoStorage` as today |
| Phrase ticks | Worked out in the browser from the pending proposal (see [Phrases view](#phrases-view)) |

The snapshot's fields for each listing: `listing_id`, title, shop name,
whether it is your shop, score (0–100), listing review count, favourites per
day, views per day, shop `review_average`, tags, lead and thumbnail URL.
It also holds the queries, found and scored counts, `searched_at` (the source
of the header's relative time), and the ranked phrase list.

---

## 6. Settled details

- **Leaving the editor** doesn't stop the chain. On return, the editor
  reattaches, and the indicator, panel and drawers come back as they were.
- **Before the first run**, no panel is rendered. An empty "run AI Mode to see
  the market" card would be noise on every new listing.
- **Re-running** drops the panel to `loading` straight away. A failed re-run
  shows the failure note; the previous snapshot stays on disk and comes back
  on reload.
- **Narrow screens.** Below 1100px the panel stacks under the fields at full
  width and isn't sticky. Narrow windows are rare for this desktop app.

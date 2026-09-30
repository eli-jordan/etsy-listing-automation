# This project's slide layouts and house rules

The agent reads BOTH the shipped doctrine (instructions/slides.md) and this
file - and this file WINS where they disagree. Add your own layouts, house
rules, and banned moves here; it is yours and marver never touches it.

To grow it from examples: drop decks (PPTX, PDF, screenshots) into
design/slides-inspiration/ and ask the agent to "study my inspiration" -
it will propose additions here for your review.

## The deck look

How a deck wears this brand. The agent drafts it from DESIGN.md and
theme.css on the first deck (a reviewed edit, building on provisionally
with the theme's tokens); anything it cannot settle stays `TBD` for you.
Each line shows the shape with an example - replace the example, keep the
shape.

- **Tokens** (`--marver-slide-*` in theme.css, read by the Slide root):
  ground / ink / muted, each with a `-dark` twin; accent, one value for
  both themes. e.g. ground = the page background, ink = the heading
  colour, accent = the primary button.
- **Type** (`--marver-slide-font`): one family, the theme's; the type
  roles carry their weights. e.g. Inter.
- **The mark**: which asset, where, how big. e.g. wordmark SVG, bottom-left
  of the cover and the closing only, 120px wide - never on content slides.
- **Colour meaning** (charts, cards, badges): hue = category, fixed across
  the deck. e.g. accent = us, slate = competitors, muted = the baseline;
  green / amber / red reserved for status.
- **Backgrounds allowed**: e.g. the flat ground; a theme gradient on covers
  and sections only; no photos behind text without a scrim.
- **Imagery**: e.g. product screenshots on a device-less frame, real people,
  no stock; illustrations in the product's line style only. Evidentiary
  images (a report fragment, a log line, a reasoning trace, a real
  screen) are evidence objects, not decoration - hero material when the
  message warrants it.
- **Tempo** (`--marver-slide-tempo`): e.g. 350ms - one value, every deck.
- **Numbers**: e.g. $ and k / M (lowercase k), fiscal years as FY26,
  negatives in brackets, one decimal on percentages.
- **Voice**: three words the deck sounds like, and the words it never
  uses. e.g. direct, warm, specific; never "leverage", "seamless", "journey".
- **Terminology**: user-facing word → never-shown internal word.
  e.g. "Comments" → "Enrichment".
- **End card**: yes / no. e.g. yes - the mark on the ground, no text; the
  ask lives on the slide before it.

## Layouts

(none yet - the shipped recipe list and atlas apply)

## House rules

(none yet)

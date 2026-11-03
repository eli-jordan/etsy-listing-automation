---
name: etsy-research-design
description: Design research for a niche on Etsy, ending in 20 new t-shirt (or other print) design ideas. Samples Star Seller and Bestseller search results for the general product category and for the niche, analyses the designs on the top listings (themes, tone, style, layout, typography, elements, colours, phrase templates), and crosses what wins in the general category with what wins in the niche. Use when the user wants design ideas for a niche, or asks what designs, styles or phrases sell in a category.
---

# Design research on Etsy

The signal: designs on listings that Etsy marks as Star Seller or Bestseller are designs that sell. This skill samples two sets of them:

- **general**: the whole product category ("t-shirt", "funny t-shirt"), where the strongest styles and phrase templates in the market show up;
- **niche**: the user's niche ("teacher shirts", "dog mom tee").

It annotates each set's top designs into tags, weighs the tags by listing performance, and looks for **crossovers**: patterns proven in the general category that the niche hasn't used yet, applied to the niche's own subjects. The output is **20 design ideas**, each one a crossover with evidence behind it.

Follow the [etsy-research](../etsy-research/SKILL.md) skill for the mechanics this builds on: loading the Claude in Chrome tools, pacing, and the API script. If the Chrome tools aren't in the session, stop and tell the user; this research needs the Star Seller and Bestseller filters, which only etsy.com has.

## 1. Niche and product

Get the niche from the user's request. If they gave none, ask before doing anything else. The product defaults to t-shirts; take sweatshirts, hoodies, mugs and so on from the request.

## 2. Queries

Write two lists, each naming the product so results stay on it:

- **general**: 3–5 broad queries for the product, e.g. `t shirt`, `funny t shirt`, `graphic tee`, `retro t shirt`, `gift shirt`.
- **niche**: 4–8 queries a buyer in the niche would type, covering its main angles without near-repeats.

Use "retro" rather than "vintage": Etsy routes "vintage" queries into its Vintage category (real items 20+ years old). Show both lists to the user in one line and continue.

## 3. Sample the search pages

Runs live under `C:\Users\Admin\Downloads\etsy-design-research\`:

- general: `general-<product>-<YYYY-MM-DD>\`. **Reuse** an existing general run for the same product up to 14 days old whose `plan.json` holds 3 or more queries, skipping its sampling, fetching and annotation; the general category changes slowly.
- niche: `<niche-slug>-<YYYY-MM-DD>\`.

Plan each run that needs sampling (skip the plan when `plan.json` already exists, i.e. on a resume):

```bash
uv run python .claude/skills/etsy-research-proven-mockups/sample_plan.py plan RUN_DIR "query 1" "query 2" ...
```

Each query gets a Star Seller page and a Bestseller page, newest first. Then run the page loop and the block handling exactly as in [etsy-research-proven-mockups](../etsy-research-proven-mockups/SKILL.md) step 3, on the general run first, then the niche run. If the Chrome extension disconnects mid-loop, the open tab is lost with it: get a fresh tab from `tabs_context_mcp` and carry on with the same page. For a scheduled continuation, use the title `Resume Etsy design research` and the prompt `Resume the etsy-research-design run for <niche> (general: <GENERAL_DIR>, niche: <NICHE_DIR>): invoke the etsy-research-design skill and continue from step 3. The plans already exist.`

## 4. Fetch and tile

For each run, from the repo root:

```bash
uv run python .claude/skills/etsy-research-proven-mockups/fetch_listings.py RUN_DIR --images 2
uv run python .claude/skills/etsy-research-design/design_sheets.py sheets RUN_DIR [--match WORDS] [--exclude WORDS]
```

`fetch_listings.py` looks the listings up through the API and downloads two images each. `sheets` ranks them by performance score (favourites, views, Bestseller and Popular-now badges; the formula is in the script) and tiles the top 60 into `RUN_DIR\sheets\NN.jpg`, six listings per sheet. Each cell shows rank, listing ID, score, favourites, badges, shop and title above the first two images.

For the **niche run, always pass `--match`** with comma-separated words that mark the niche in a title (`teacher,teach,school,classroom,educator`). Etsy's filtered search is loose: in a "teacher shirt" test, 8 of the top 12 results were unrelated (an F1 calendar, a fantasy-novel sweatshirt, a winter-trees design). The filter matches titles only, because sellers pad tags with niche keywords on unrelated designs. The general run takes no `--match`.

The shop doesn't offer personalisation yet, so pass `--exclude custom,personaliz,personalis,your photo,your text,your name,monogram,with name,names` on **both runs** unless the user asks to include custom designs. Some personalised listings don't say so in the title; the photos give them away ("Custom birth month/year" badges, a name on every shirt), so mark those `off_topic` while annotating. Sets where the buyer picks one of a fixed list of designs ("Most Likely To" quote packs, mugshot sets) are not custom.

Results mix tees, sweatshirts and hoodies whatever the query says. The design is what matters here, so keep them all.

## 5. Annotate

Read every sheet of a run in order and write one JSON line per listing to `RUN_DIR\designs.jsonl`. The step is done when every listing in `sheets\index.json` has a line; `tally` warns about any that don't.

```json
{"listing_id": 1800226651, "text": "Most Likely To Tell Dad Jokes", "pattern": "Most Likely To ___", "theme": ["christmas", "family"], "tone": ["funny"], "style": ["bold text-only"], "layout": ["stacked lines"], "typography": ["chunky sans", "script accent"], "elements": ["candy cane", "holly"], "colours": ["red", "green", "white"]}
```

- **text**: the exact words printed on the design; null for none. When the photo makes it unreadable, the title usually carries it; open the image file for a closer look if neither does.
- **pattern**: the phrase as a reusable template with `___` for the swappable part ("In My ___ Era", "___ Mode: On", "Just A Girl Who Loves ___", "Professional ___er"). Null when the text has no reusable shape.
- **theme**: the subjects and occasions (`dog`, `teacher`, `halloween`, `coffee`).
- **tone**: `funny`, `sarcastic`, `cute`, `sentimental`, `motivational`, `edgy`, `wholesome`, `ironic`.
- **style**: the overall look, e.g. `retro sunset`, `distressed varsity`, `bootleg rap tee`, `hand-drawn doodle`, `bold text-only`, `minimal line art`, `vintage illustration`, `text and character`, `parody`, `watercolour`, `groovy 70s`, `y2k`, `vintage badge`, `custom photo`. Tag production finishes too: `embroidered`, `glitter puff`.
- **layout**: `centered icon`, `text above character`, `arched text over icon`, `stacked lines`, `single word`, `script over varsity`, `repeated text`, `circle badge`, `left chest`, `back print`, `full front graphic`.
- **typography**: `chunky sans`, `condensed serif`, `script`, `varsity slab`, `retro bubble`, `handwritten`, `outline`, `distressed`.
- **elements**: the drawn things: `smiley face`, `skull`, `stars`, `checkerboard`, `flowers`, `coffee cup`, `lightning bolt`.
- **colours**: the print's palette by plain name, plus `garment: <colour>` for the shirt.

Tags are lowercase and short. Reuse the exact spelling of a tag already written in either run, since `tally` counts identical strings; extend the lists above when a design needs a tag they lack. Set `"off_topic": true` (other fields optional) on listings the tally should ignore:

- in either run, anything that isn't apparel with a design: golf tees, calendars, quilts, light-up shirts;
- designs built on licensed characters, brands or shows, since their sales come from the licence;
- personalised designs the `--exclude` filter missed;
- in the niche run, designs that aren't about the niche, which `--match` lets through when a title mentions it in passing ("Custom logo sweatshirt, team staff shirt").

## 6. Tally

```bash
uv run python .claude/skills/etsy-research-design/design_sheets.py tally GENERAL_DIR NICHE_DIR
```

It prints one table per field: each tag's performance-weighted support in each run, with shop counts, and writes `tally.json` into the niche run. It counts only listings on the current sheets, so after re-running `sheets` with different filters, annotate the listings that moved into the top 60 and the old notes for dropped listings are ignored. A shop's best listing counts in full and its other listings a quarter, so one shop's product line can't dominate. Tags strong in the general run and absent from the niche run are flagged **gap**: those are the crossover candidates. A tag weak in both but seen on one very high-scoring listing is worth a look on the sheets too.

Style, layout, typography, tone and pattern gaps carry over directly. A theme gap is a subject, so it carries over only where it fits the niche: a frog character can teach a class, but a `christmas` gap mostly reflects the season the general run was sampled in.

## 7. Ideas

Write 20 design ideas. Each one is a **crossover**: at least one proven general-run tag (preferably a gap) applied to a proven niche theme or subject. Spread them across different gaps and patterns; no more than three ideas on any one pattern or style.

Every idea passes these checks:

- **Original**: its text appears on no listing in either `designs.jsonl`, and it isn't a niche listing's design with the words swapped.
- **Not saturated**: take two counts with `uv run python .claude/skills/etsy-research/etsy_api.py listings/active keywords="<words>" limit=1`, which returns a `count`:
  - **phrase**: the idea's exact text. Tens or fewer means nobody sells it yet; hundreds means it's taken, so rework the wording.
  - **template**: the pattern's fixed words plus the niche and product (`most likely to teacher shirt`). This measures how crowded the template is in the niche. In testing, `most likely to teacher shirt` returned 2,202 and `three moon teacher shirt` returned 14, while the phrase `most likely to confiscate your phone` returned 0. A fresh phrase on a crowded template is a weaker idea, so rank it lower.
- **Clean**: no trademarked names, characters, logos, lyrics or brands (Disney, sports teams, bands, film quotes).
- **Printable**: one or two print colours where the style allows, readable at chest size. Render an embroidered or glitter-puff winner as a print that suggests the finish (stitched outline, faux glitter texture).

Each idea carries:

- a short name
- the exact text, if any
- the visual: style, layout, typography, elements, print colours, garment colour
- the crossover: which general tags and which niche tags it combines, with their weights from `tally.json`, and one or two example listing IDs from each run
- the phrase and template counts

## 8. Codex briefs

Each idea gets a hand-off folder, `NICHE_DIR\ideas\NN-slug\`, for a Codex agent that generates the artwork with ChatGPT Image 2.

1. **Pick 1–3 style references** per idea from the listings its crossover cites: the images that best show the look the idea borrows (rendering, layout, lettering), not its subject. Use `ID:2` when the first image is a size chart or a mockup that hides the design.
2. **Download them** at full size:

   ```bash
   uv run python .claude/skills/etsy-research-design/design_sheets.py refs NICHE_DIR/ideas/NN-slug/refs ID[:RANK] ... --runs GENERAL_DIR NICHE_DIR
   ```

   Tile all the refs into one image and look at it. Every reference should show the design, not a chart, a collage of colour options or a crowded flat lay.
3. **Write `prompt.md`** from [codex-brief.md](codex-brief.md), one line per reference saying which quality to take from it. Fill every `{…}`; the requirements and checks stay as written. The brief asks for 3 distinctly different designs as transparent 4500×5400 PNGs.

## 9. Report

Write `NICHE_DIR\ideas.md`:

1. **General category**: the top 5 tags per field, with weights and shop counts.
2. **Niche**: the same.
3. **Gaps**: the flagged tags, with the general listings that show them.
4. **Ideas**: the 20, ranked by how strongly the evidence backs them.

End `ideas.md` with a **Codex hand-off** table linking each idea's `prompt.md` and listing its reference IDs.

Reply to the user with the folder path, a 3–5 line summary of what wins in each set, and the 20 ideas as a table (name, text, visual in one line, crossover). Embed the two most useful sheets, one per run, with Markdown image syntax and absolute paths.

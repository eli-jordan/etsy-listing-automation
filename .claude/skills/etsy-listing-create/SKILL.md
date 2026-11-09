---
name: etsy-listing-create
description: Turn design PNGs into new draft Etsy listings, ready for the seller's review. Creates them as a batch, then sets colours, the gallery, mockup positions, title, tags and lead. Use when the user asks to create, set up, prepare or finish new listings from designs.
---

# Listing setup

Takes design PNGs to draft listings the seller can review in the app. Setup ends at a local draft, so leave `plan`, `apply` and deploys to the seller.

Run the scripts from the repo root with the repo's Python:

```bash
uv run python .claude/skills/etsy-listing-create/scripts/setup.py COMMAND ...
```

The scripts default to the app at `http://127.0.0.1:8000`, so pass `--url` before the command for any other port. `$ROOT` is the workspace that app serves. Give each listing its own output folder, such as `<work>/<name>`, because several runs may share a parent folder.

Every write goes through `setup.py` or the SEO skill's `draft`. Each prints any `FIELD ERRORS` or `BLOCKS` it gets back, and a save is only done when it prints `saved`. Until step 5, it also lists the empty title and lead under `copy still to write`, which doesn't stop a save.

## 1. Create the listings

```bash
setup.py health --root $ROOT
setup.py create --template "<listing template>" --prefix <prefix> --strip-variant <PNG files>
setup.py briefs <batch id>
```

Use the naming convention the existing listings follow, for example `christmas-2026-`. `--strip-variant` drops a trailing `-a` or `-b` variant letter from file names. A staging problem leaves the batch unconfirmed and prints why. `briefs` waits for the app's AI to draft each brief, then prints them.

For each listing, run `setup.py look <name> --root $ROOT --out <dir>`. It prints the brief and section, and writes `design-*.jpg`, the design on grey, dark and light backdrops. Image viewers flatten transparency, so read that file rather than the PNG. The copy steps treat the brief as fact, so correct anything it gets wrong, especially the exact printed words and anything it calls a background, with `setup.py brief <name> --file <path>`. Also check that the section suits the design, because the template stamps one section on every listing.

Done when every listing exists and every brief matches its design.

## 2. Choose colours

```bash
uv run python .claude/skills/etsy-listing-create/scripts/colour_sheet.py --root $ROOT --name <name> --out <dir>
```

It prints a ranked list and the three nearest finished listings, and saves both in `colours.json`. It also writes `swatches.jpg`, with the design on every colour the garment sells. Dual-artwork listings show the right file on each shirt.

Read `swatches.jpg` at normal size and pick 6 to 10 colours, or 4 to 12 when the design calls for it. Judge each shirt the way the seller does:

- The whole design reads at a glance. Small text and captions are what fail first, so look at them on every shirt, because the ranked score can't see them.
- The shirt suits the design's palette and mood, and the set gives a buyer real variety rather than near-duplicates.
- The precedents show the seller's taste, and the score is only evidence. A low-ranked colour that clearly works is fine.

Done when you've looked at every colour in the set, and you have a one-line reason for each top-8 colour you dropped.

## 3. Build the gallery

```bash
setup.py gallery <name> --colours a,b,c --hero b --variation <template> --scenes <t1>,<t2>:<colour>,...
```

`gallery` writes the shop's gallery shape: hero, video, size guide, lifestyle scenes, info card, then one variation tile for each other colour. It also enforces Etsy's limit of 20 images, so each extra colour leaves room for one less scene. A bare scene name takes the next colour in turn.

Choose the variation template, the hero colour and 5 to 9 scenes from [reference/templates.md](reference/templates.md). The hero is the shirt that sells the design best at thumbnail size. Some colours look different in a photo than on a swatch, so confirm the hero and scene colours on the sheet in step 4. A colour may appear in more than one scene.

Done when `gallery` prints `saved`.

## 4. Check the mockups

```bash
uv run python .claude/skills/etsy-listing-create/scripts/mockups.py sheet <name> --out <dir>
uv run python .claude/skills/etsy-listing-create/scripts/mockups.py zoom <name> <template> <colour> --out <dir>
```

Read `sheet.jpg` at normal size, and zoom any scene you're unsure of before you judge it. Fail only what a buyer would notice:

- art cut off, or hidden by an arm or fold;
- art sitting too high or too low on the chest;
- text too small or too faint to read;
- a shirt colour that looks wrong in the scene.

Fix a fault by swapping the scene or colour with `gallery`, or by moving the print:

```bash
setup.py position <name> --root $ROOT <template>:<scale>[:<dy>[:<dx>[:<degrees>]]]
setup.py position <name> --root $ROOT --clear <template>
```

Moves work in the template box's own frame, as fractions of its width and height, and negative `dy` raises the print. The limits are in `$ROOT/settings.yaml`, and a move past them prints `BLOCKS`. Keep the mockup an honest picture of the printed shirt: move a print to correct where a scene puts it, not to make small art look bigger. Look at the regenerated sheet after each round. [reference/templates.md](reference/templates.md) lists the scenes known to need moving, and the ones that stretch round art.

Done when the sheet has no buyer-visible fault, within two fix rounds. Note anything left for the seller.

## 5. Write the title, tags and lead

Once every listing has passed step 4, run the [etsy-listings-optimize-seo](../etsy-listings-optimize-seo/SKILL.md) skill's **new listings** branch on the whole batch together. Its eRank and autocomplete work runs in batches, so one run covers every design. Its scope is the batch's names, such as `christmas-2026-<slug>`.

The lead is one sentence. It names who the shirt is for and what the design shows, from the brief, and it ends with the garment. It opens with the title's two lead terms, which the SEO skill checks.

Done when `setup.py check <names>` shows every listing with 13 tags, a title, nothing under `copy still to write`, and `clean`.

## 6. Report

Finish with one row per listing: colours, hero, any print moves, title, and the path to its `sheet.jpg`. Then list what the seller should look at first: brief fixes, tags kept without data, leftover mockup notes, and anything uncertain. Say that the listings are local drafts, and that `plan` and `apply` remain the seller's to run.

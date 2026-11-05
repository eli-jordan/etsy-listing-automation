---
name: create-mockup-template-cc1717
description: Generate the 33 Comfort Colors 1717 colour versions of one or more mockup photos with Nano Banana 2.1 2K, cleaning off any design or labels first, then hand each export to ingest-mockup-templates.
disable-model-invocation: true
---

# Overview

Turns one or many source mockup photos into the full Comfort Colors 1717 colour set, one recolour per garment colour. Each result is an export in the shape [ingest-mockup-templates](../ingest-mockup-templates/SKILL.md) reads.

In the commands below, `recolour.py` and `kie.py` mean `uv run python .claude/skills/create-mockup-template-cc1717/<script>`, run from the repo root.

# Generating

Every image is Nano Banana 2.1 at 2K. Its brief, minus `##` headings, is the whole prompt, so write anything you append as instructions to the generator, without scores.

- **Kie.ai**, the default: `kie.py`, below. Regenerating means naming the slugs: with none, `kie.py colours` only fills in missing photos. A replaced photo stays in `out\` as `<slug>-roundN.keep`.
- **Kittl**: when `kie.py` reports Kie.ai is out of credits, ask the user whether to switch. If so, check `kittl-get-token-balance` covers the images, at about 20 tokens each. Upload each input through `kittl-upload-image`'s presigned URL, then call `kittl-generate-media` with the 2K Nano Banana 2.1 model, `1:1`, and the upload as `referenceImages`, at most 10 at once. Download each result to the path `kie.py` would use, keeping any replaced photo the same way.

# One or many source images

Given one image, you are the coordinator.

Given more than one, launch one coordinator delegate per image, at most 2 at once. Give each this file's path. Report a status table of all the images as coordinators report back. Coordinators hand back whatever needs the user: crops to approve, failed reviews, finished sheets and Kie.ai running out of credits. Ask about credits once, and pass the answer to every coordinator.

# Process for one source image

## 1. Prepare the source

The result is one blank 2048x2048 image, with no design on the garment and no labels or stickers on the photo.

1. If the photo isn't square, crop it and get the user's approval.
2. Open the photo and look at the whole shirt and the whole frame. List everything to remove: any print, text, logo, graphic or design on the shirt, and any overlay on the photo (a colour-name label, a watermark, a sticker). A brand label inside the collar stays.
3. If the list is empty, resize the photo to 2048x2048 if needed and go to section 2. Otherwise clean it, below.

Note the shirt's current colour for section 2.

### Cleaning a source

Work in `CLEANUP_DIR`, `C:\Users\Admin\Downloads\mockup-recolours\cleanup-<scene-slug>-<YYYY-MM-DD>\`, with the photo copied in as `original.<ext>`.

1. Write `brief.md` from [cleanup-brief.md](cleanup-brief.md). `{removals}` is a bulleted list of each item and where it is ("the "IVORY" label in the top-left corner, white box included"; "the printed design on the shirt's chest, four candy apples with bows"). Generate from it:

   ```sh
   kie.py edit CLEANUP_DIR/original.<ext> CLEANUP_DIR/brief.md CLEANUP_DIR/out/generated.png
   ```

2. Composite and check it:

   ```sh
   recolour.py clean CLEANUP_DIR/original.<ext> CLEANUP_DIR/out/generated.png --out-dir CLEANUP_DIR
   ```

   It blends only the removed items onto the original as patches. It writes `cleaned.png` and, per patch, `clean-patch-N.jpg`: original, cleaned, and cleaned at contrast x4. It exits non-zero and prints the reason when a patch fails a check.

3. Open every `clean-patch-N.jpg` and look for any trace of the removed items: a tint, an outline, a fleck, a shape in the x4 view. Then check `cleaned.png` whole: blank, with nothing else disturbed.

4. On any failure, append a `## Review` section to `brief.md` saying what to remove and where, regenerate, and repeat from step 2. After three failed rounds, stop and show the user the patch reviews.

The passing `cleaned.png` is the source for the rest of the run.

## 2. Prepare the run

The scene name is a terse description of the source image (`woman sitting cross legged`). Runs live under `C:\Users\Admin\Downloads\mockup-recolours\<scene-slug>-<YYYY-MM-DD>\`.

```sh
recolour.py prepare SOURCE \
  --scene "woman holding a bag" --run-dir "C:\Users\Admin\Downloads\mockup-recolours\woman-holding-a-bag-2026-11-04" \
  [--source-colour White]
```

It copies the source to `source.png`, writes one brief per colour to generate, `briefs\<colour-slug>.md`, for the photo `out\<colour-slug>.png`, and prints two **pilot** briefs: White and Black.

Pass `--source-colour` when the source shirt is already a palette colour. That colour gets no brief, and the source is copied to its `out\` file. If it's White, Ivory replaces White as a pilot. If it's Black, Pepper replaces Black.

## 3. Pilot

You review the pilots yourself; the user is not asked.

Generate the pilots and build the review:

```sh
kie.py colours RUN_DIR PILOT_SLUG PILOT_SLUG
recolour.py pilot RUN_DIR
```

It writes to `review\pilot\`:

- `tile-*.jpg`, full-resolution tiles over the shirt and its surroundings, each showing the source beside both pilots.
- `outline.jpg`, the source with the proposed shirt outline in green.
- `outline-mask.png`, that outline as a mask, white for shirt.

## 4. Review the pilots

### Check the photos

Open every tile. The pilots pass only when each tile shows them matching the source in everything but the shirt's colour:

- **Shape**: sleeves, shoulders, collar and hem neither grow nor shrink. Nothing hidden in the source (behind hair, arms, hands or props) becomes visible shirt, and background showing in the source, between hair strands or around the arms, stays background.
- **Everything else**: face, hair, hands, jewellery, other clothing, background and framing are unchanged, not just similar.
- **The shirt**: blank, evenly the pilot colour, its folds and lighting following the source.

On any discrepancy, append a `## Pilot review` section to the brief of each pilot that shows it, saying what the source shows there, in terms of this photo. Regenerate those pilots and repeat from the `pilot` command. After three failed rounds, stop and report the remaining discrepancies to the user with the tiles that show them.

### Check the outline

An outline fault needs a correction, not a regeneration. Open `outline.jpg` and check the green line follows the shirt's real edge all the way round, with hair, arms, props and background outside it. The line shows outer edges only, so open `outline-mask.png` for the holes inside the shirt. `pilot` also prints:

- **Band spill**: the share of the 24px just inside the edge that looks wrong in both the source and the pilot furthest from it. It warns at 16% or more. This is advice, and it only catches outlines that are too big.
- **Largest disagreement** with the old automatic outline, boxed in magenta on `outline.jpg`. Look inside the box and decide which outline is right there.
- **Fell back**: the automatic cut failed, so the outline is the pilot's changed pixels alone. Expect to correct it.

Correct the outline whenever it leaves the shirt's real edge. Start from `outline-mask.png` and build a mask at the source's framing, any square size, white for shirt and black for the rest:

- Keep changed pixels that also match the shirt in the source, when its colour stands apart from its surroundings (a dark neutral shirt, a red shirt).
- Keep where several pilot rounds agree, when colour can't separate shirt from surroundings.

### Approve

When the photos and the outline pass:

```sh
recolour.py pilot RUN_DIR --approve
```

With a corrected mask, add `--reference MASK.png`, then open `review\pilot\outline-manual.jpg` and check it the same way. A later plain `--approve` refuses to overwrite that mask, and a new `--reference` replaces it.

Approving saves the outline as `garment-reference.png`, which `assemble` composites with and drift is measured against. It also copies every `## Pilot review` section into the other briefs, so word them for any colour.

## 5. Generate the rest

```sh
kie.py colours RUN_DIR
```

It lists any failures. Run it again for those.

## 6. Assemble and review

```sh
recolour.py assemble RUN_DIR
```

It composites each `out\` photo, inside the approved outline, over the source, so everything outside the shirt keeps the source's pixels. It writes the composites to `export\` and tiles them into `review\sheet-NN.jpg`. Each cell shows the target swatch, a **measured** swatch (the median colour of the shirt area) and these figures, which are the verdict:

- **Drift**: the percentage of the frame the raw recolour changed outside the shirt, ignoring a 16px band around it and isolated specks. The limit is 1%. A failure writes `review\drift-<colour>.png`, with the drift in magenta.
- **Lighting** and **folds**: how well the shirt's shading follows the source or an approved pilot, whichever is nearest in brightness. The minimums are 0.5 lighting and 0.3 folds. A failure writes `review\shading-<colour>.png`, with the mismatch in cyan.

It exits non-zero listing any colour that fails either check, or whose photo is missing or not 2048x2048.

Retry each listed colour before review. A missing or wrong-size photo needs only regenerating. For the others, open the map and append a `## Retry` section to the brief, saying what must match the source (the sleeve outline, the hair, the folds or the light on the shirt) and that everything but the shirt's colour stays identical to it. Regenerate it, then re-measure every colour without the export:

```sh
recolour.py drift RUN_DIR
```

After three retries of one colour, stop retrying it and flag it, with its map, in the review. Run `assemble` once every colour passes or is flagged.

Open every sheet yourself, then show them to the user with the colours worth a closer look: drift well above the rest, a measured swatch far from its target, patches of the old colour, or a print that appeared on the shirt. Measured swatches follow the photo's lighting, so compare them across colours, not to the hex alone. Then ask the user to pick one:

- **redo** named colours, with what is wrong: append a `## Reviewer notes` section with their words to each of those briefs, regenerate only those, and re-run `assemble` and this review.
- **ingest** the set now.
- **stop**, leaving the run directory for later.

## 7. Ingest

On the user's go-ahead, follow [ingest-mockup-templates](../ingest-mockup-templates/SKILL.md) with `RUN_DIR\export` as the source. Finish with its report, plus the run directory and any colours the user accepted with known flaws.

If the user provided multiple source images, then only propose the ingest when they are all complete.

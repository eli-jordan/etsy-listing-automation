---
name: etsy-research-proven-mockups
description: Find the 20 or so proven mockup photos that high-performing Etsy listings in a niche share. Samples Star Seller and Bestseller search results in the user's Chrome, groups listing images that come from the same base photo even when cropped, recoloured or overlaid, ranks the mockups by how many listings use them and how well those listings perform, and downloads them at full resolution. Use when the user wants proven, popular or best-selling mockups, or the mockup or model photos competitors use, for a topic or niche.
---

# Proven mockups on Etsy

The signal: when several shops that Etsy marks as Star Sellers or Bestsellers put their designs on the same base photo, that photo is a proven mockup for the niche. This skill samples those listings, groups their images by base photo, and returns **about 20 mockups**. They're ranked by how many listings use each one and how well those listings perform.

Follow the [etsy-research](../etsy-research/SKILL.md) skill for the mechanics this builds on: loading the Claude in Chrome tools, pacing, and the API script. If the Chrome tools aren't in the session, stop and tell the user; this research needs the Star Seller and Bestseller filters, which only etsy.com has.

## 1. Topic

Get the niche from the user's request ("Christmas tees", "teacher sweatshirts", "dog mom shirts"). If they gave none, ask before doing anything else.

## 2. Queries

Write 3–10 search queries a buyer in that niche would type, covering its main angles without near-repeats: for Christmas tees, `christmas tee`, `christmas shirt`, `funny christmas shirt`, `retro christmas t-shirt`, `family christmas shirts`. Name the garment in each query so results stay on it. Reaching 20 mockups usually takes 8–10 queries; a 2-query test gave 9 real mockups. Use fewer only for a narrow niche. Show the list to the user in one line and continue.

## 3. Sample the search pages

Each query gets two pages, newest first: one filtered to Star Sellers (`is_star_seller=true`) and one to Bestsellers (`is_best_seller=true`). Etsy restricts access for a few minutes when searches come too fast, so pages load one at a time, each in a fresh tab, with jittered waits. [sample_plan.py](sample_plan.py) holds the plan, picks the waits and works out retries. A page counts as done once its file exists, so a run resumes wherever it stopped.

**Plan** (skip when `RUN_DIR\plan.json` already exists, i.e. on a resume). The run directory is `C:\Users\Admin\Downloads\etsy-mockup-research\<topic-slug>-<YYYY-MM-DD>\`:

```bash
uv run python .claude/skills/etsy-research-proven-mockups/sample_plan.py plan RUN_DIR "query 1" "query 2" ...
```

**Loop over the pages:**

1. Run `sample_plan.py next RUN_DIR`. It prints `{"done": true}`, which means go to step 4, or the next page: `file`, `url`, `wait_before` and `wait_after_load` (lists of seconds, each at most 10).
2. Open a fresh tab with `tabs_create_mcp`, then close the previous page's tab, if any. Opening first keeps the tab group alive. Call `tabs_context_mcp` with `createIfEmpty` once at the start of the session.
3. In one `browser_batch` on the new tab:
   - a `computer` `wait` for each `wait_before` entry
   - `navigate` to `url`
   - a `wait` for each `wait_after_load` entry
   - `javascript_tool` with the contents of [extract_search_cards.js](../etsy-research/extract_search_cards.js)
4. Act on the extractor's output:
   - **Header plus listing IDs:** save it, unchanged, to `file`. If the header says `part=1/2`, run the extractor again with `PART = 2` and append that line too.
   - **`error: no search results grid`:** wait 10 seconds and extract again. If it still fails, take a screenshot. A normal page with zero results is done: save the single line `count=0`. Anything else, stop and tell the user.
   - **`blocked:`:** Etsy has restricted access. Follow the block steps below.
5. Repeat.

**On a block:** close the tab, then run `sample_plan.py blocked RUN_DIR`.
- **It prints `retry`, `minutes` and `run_at`:** schedule a one-off continuation with T3's `schedule_task`:
  - `schedule: {type: "once", runAt: <run_at>}`
  - `bindToCurrentThread: true`
  - title `Resume Etsy mockup sampling`
  - prompt: `Resume the etsy-research-proven-mockups run in <RUN_DIR>: invoke the etsy-research-proven-mockups skill and continue from step 3. The plan already exists.`

  Tell the user the retry number and time, then end the turn. The script backs off 15 → 20 → 30 → 45 minutes, each with ±20% jitter, while no page succeeds between blocks, and starts over at 15 once one does.
- **It prints `abort`:** the 45-minute retry was blocked too. Stop. Tell the user how many pages are saved, and offer to analyse those or to resume later with `next`.

A scheduled continuation is a new session, so load the Chrome tools again first. Once `next` prints `done`, carry on through steps 4–7 in the same run.

## 4. Fetch listings and images

From the repo root:

```bash
uv run python .claude/skills/etsy-research-proven-mockups/fetch_listings.py RUN_DIR
```

It looks every listing up through the API and drops digital downloads. It records each listing's favourites and views, and which searches, filters and badges surfaced it. Then it downloads the first 6 images per listing at 570px (`--images N` to change that). About 170 listings take 2 minutes.

## 5. Group and rank

```bash
uv run --script .claude/skills/etsy-research-proven-mockups/cluster_mockups.py cluster RUN_DIR
```

The script has its own dependencies (torch, open_clip, OpenCV); the first run installs them. It:

1. collapses repeats of one photo inside a listing (colour variants, re-crops) into one image, which roughly halves the comparisons;
2. drops size charts, colour charts (including grids of one design in many shirt colours), font and thread pickers, and order-instruction cards, by CLIP zero-shot labels. About a quarter of all images go;
3. finds each image's look-alikes in other shops with CLIP, the chest blurred so the printed design doesn't drive the match;
4. confirms each pair with SIFT keypoints outside the chest under a crop/zoom/shift model, so a match means the same photo, not just a similar scene;
5. keeps groups that span 2+ shops and ranks them by score.

**Scoring.** Each listing gets a performance score:

```
log10(1 + favourites) + 0.5 × log10(1 + views) + 1 (if Bestseller) + 0.5 (if Popular now)
```

- **Bestseller** means the badge showed on the card, or the `is_best_seller` search surfaced the listing (each card shows only one badge).
- **A mockup's score** is the sum of its listings' scores. Each shop's best listing counts in full and that shop's other listings count a quarter, because one shop reusing its own mockup is weak evidence.

So a mockup ranks high when many listings use it, when those listings perform well, or both. The weights are constants at the top of the script.

It prints the ranking (score, shops, listings, favourites, views, Bestsellers, Popular now) and writes:
- `clusters.json`
- `clusters\overview.jpg`: one tile per group, labelled `#N score S Xsh Yli`
- `clusters\NN.jpg`: each group's members by listing score, labelled shop, listing score and favourites
- `clusters\dropped-charts.jpg`: what the chart filter removed

## 6. Review the groups

The script finds and ranks the groups; you decide which are real mockups. Glance at `dropped-charts.jpg` first: if it shows a model or flat-lay photo, the filter removed a mockup, so tell the user. Then read `overview.jpg` and each candidate's `NN.jpg` in ranked order until 20 groups pass:

- **Drop non-mockups the filter missed:** charts, care cards, "how to order" graphics, text-only images.
- **Drop wrong members:** a member from the same photoshoot but a different pose or framing is a different photo. If removing it leaves fewer than 2 shops, drop the group. If it held the group's best listing, the group's real rank is lower.
- **Merge** groups that are the same photo the script split, and add up their scores.
- **Name** each group by what a buyer sees: model, pose, garment colour, props, setting, e.g. "Woman cross-legged in a pepper tee and jeans, white sneakers".

Keep the script's order apart from those corrections. If fewer than 20 pass, report the ones that did and offer a second run with new queries.

## 7. Download and report

For each of the 20 mockups, in ranked order:

```bash
uv run --script .claude/skills/etsy-research-proven-mockups/cluster_mockups.py download RUN_DIR CLUSTER "short-name"
```

This saves the largest full-resolution image from each of up to 4 listings (`--max N`) to `RUN_DIR\final\NN-short-name\`.

Write `RUN_DIR\final\README.md` with one row per mockup, in ranked order:
- name and score
- shops and listings
- total favourites and views
- Bestseller and Popular-now counts
- the listing URLs (from `clusters.json`)

Then reply to the user with the run folder path, the ranked table, and two images per mockup from different shops, embedded with Markdown image syntax and absolute paths.

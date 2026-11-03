---
name: etsy-research-proven-mockups
description: Find the mockup photos that high-performing Etsy listings in a niche share. Samples Star Seller and Bestseller search results in the user's Chrome, groups listing images that come from the same base photo even when cropped, recoloured or overlaid, and downloads the top 10–15 mockups at full resolution. Use when the user wants proven, popular or best-selling mockups, or the mockup or model photos competitors use, for a topic or niche.
---

# Proven mockups on Etsy

The signal: when several shops that Etsy marks as Star Sellers or Bestsellers put their designs on the same base photo, that photo is a proven mockup for the niche. This skill samples those listings, groups their images by base photo, and returns the photos used most widely.

Follow the [etsy-research](../etsy-research/SKILL.md) skill for the mechanics this builds on: loading the Claude in Chrome tools, pacing, and the API script. If the Chrome tools aren't in the session, stop and tell the user; this research needs the Star Seller and Bestseller filters, which only etsy.com has.

## 1. Topic

Get the niche from the user's request ("Christmas tees", "teacher sweatshirts", "dog mom shirts"). If they gave none, ask before doing anything else.

## 2. Queries

Write 3–10 search queries a buyer in that niche would type, covering its main angles without near-repeats: for Christmas tees, `christmas tee`, `christmas shirt`, `funny christmas shirt`, `retro christmas t-shirt`, `family christmas shirts`. Name the garment in each query so results stay on it. Show the list to the user in one line and continue.

## 3. Sample the search pages

Create a run directory, `C:\Users\Admin\Downloads\etsy-mockup-research\<topic-slug>-<YYYY-MM-DD>\`, with a `pages\` folder inside.

For each query, load two pages in one Chrome tab, newest first:

```
https://www.etsy.com/search?q=<query>&explicit=1&is_star_seller=true&order=date_desc
https://www.etsy.com/search?q=<query>&explicit=1&is_best_seller=true&order=date_desc
```

On each page, run [extract_search_cards.js](../etsy-research/extract_search_cards.js) with `javascript_tool` and save its text output, unchanged, to `pages\NN-<query-slug>-<star|best>.txt`. If the header says `part=1/2`, run it again with `PART = 2` and append the second line. Batch the pages with `browser_batch` (navigate, extract, wait 4 seconds, next) and keep to the etsy-research pacing rules. With 10 queries that's 20 page loads, the session maximum. Close the tab when done.

## 4. Fetch listings and images

From the repo root:

```bash
uv run python .claude/skills/etsy-research-proven-mockups/fetch_listings.py RUN_DIR
```

It looks every listing up through the API, drops digital downloads, records which searches, filters and badges surfaced each listing, and downloads the first 6 images per listing at 570px (`--images N` to change that). About 170 listings take 2 minutes.

## 5. Group images by base photo

```bash
uv run --script .claude/skills/etsy-research-proven-mockups/cluster_mockups.py cluster RUN_DIR
```

The script has its own dependencies (torch, open_clip, OpenCV); the first run installs them. It:

1. collapses repeats of one photo inside a listing (colour variants, re-crops) into one image, which roughly halves the comparisons;
2. drops size charts, colour charts (including grids of one design in many shirt colours), font and thread pickers, and order-instruction cards, by CLIP zero-shot labels. About a quarter of all images go, and the shared Bella+Canvas and Comfort Colors charts would otherwise top the ranking;
3. finds each image's look-alikes in other shops with CLIP, the chest blurred so the printed design doesn't drive the match;
4. confirms each pair with SIFT keypoints outside the chest under a crop/zoom/shift model, so a match means the same photo, not just a similar scene;
5. keeps groups that span 2+ shops and ranks them by shops, then listings, then favourites.

It prints the ranking and writes `clusters.json`, `clusters\overview.jpg` (one tile per group, labelled `#N Xsh Yli Zfav`), `clusters\NN.jpg` (each group's members, labelled shop, favourites and image rank) and `clusters\dropped-charts.jpg` (what the chart filter removed).

## 6. Review the groups

The script finds the groups; you decide which are real mockups. Glance at `dropped-charts.jpg` first: if it shows a model or flat-lay photo, the filter removed a mockup, so tell the user. Then read `overview.jpg` and each candidate's `NN.jpg`, going down the ranking until 10–15 groups pass:

- **Drop non-mockups the filter missed:** charts, care cards, "how to order" graphics, text-only images.
- **Drop wrong members:** a member from the same photoshoot but a different pose or framing is a different photo. If removing it leaves fewer than 2 shops, drop the group.
- **Merge** groups that are the same photo the script split, and add up their counts.
- **Name** each group by what a buyer sees: model, pose, garment colour, props, setting, e.g. "Woman cross-legged in a pepper tee and jeans, white sneakers".

## 7. Download and report

For each group that passes, in ranked order:

```bash
uv run --script .claude/skills/etsy-research-proven-mockups/cluster_mockups.py download RUN_DIR CLUSTER "short-name"
```

This saves the largest full-resolution image from each of up to 4 listings (`--max N`) to `RUN_DIR\final\NN-short-name\`.

Write `RUN_DIR\final\README.md` with one row per mockup: name, shops, listings, total favourites, Bestseller badges, and the listing URLs (from `clusters.json`). Then reply to the user with the run folder path, a table of the mockups, and two images per mockup from different shops, embedded with Markdown image syntax and absolute paths.

Point out that favourites are skewed: one popular listing can carry a group. Shop count is the better sign of a mockup that works across sellers.

---
name: etsy-listings-optimize-seo
description: Deep SEO review of the shop's Etsy listings using real eRank data, ending in an interactive report where the seller approves or rejects each tag and title change, then applying the approved ones to listing.yaml. Use when the user wants listing SEO reviewed or optimised, tags or titles improved so listings show up in active searches, or says they've finished reviewing such a report.
---

# Optimize Etsy listing SEO

Finds the tags and titles that put a set of listings in front of searches shoppers actually run, shows each proposed change with its evidence, and applies what the seller approves. A **run** covers one scope, such as the Christmas listings. A seller who has finished reviewing a report starts at step 10.

The **niche test** decides what counts as a good term: real shirt demand against few competing tees, never raw volume. `seo_review.py` applies it as **tiers**, and the report's legend explains them. **Reach** adds up shirt searches across a listing's sweet, small and busy tags.

All commands run from the repo root:

```bash
uv run python .claude/skills/etsy-listings-optimize-seo/seo_review.py COMMAND RUN ...
```

`RUN` is `<scope>-<YYYY-MM-DD>`, a folder under `C:\Users\Admin\Downloads\etsy-seo-review\`. That home also holds `keyword-store.json` and `competition-store.json`, shared by every run. Follow [etsy-research](../etsy-research/SKILL.md) for loading the Chrome tools, pacing on etsy.com and the Etsy API.

## 1. Scope

Take the scope from the request as glob patterns on listing folder names, such as `christmas-2026-*`, and ask if it's missing.

```bash
seo_review.py scope RUN "christmas-2026-*"
```

Done when `listings.json` exists and you know each listing's design from its brief, and which are drafts.

## 2. eRank access and quota

Open a new tab in the seller's main Chrome on `https://members.erank.com/listing-audit`, then `/bulk-keyword-tool`, and read both allowances. eRank pages can take a minute to draw, so wait and read again before deciding a page is blank.

- A redirect to `/login` or `/signed-out` means the seller must sign in. Ask them with AskUserQuestion, and leave the password to them. eRank signs a browser out when another computer logs in, so have them close it elsewhere.
- `32/50 left today` counts what remains, and `Quota 19/50` on an audit counts what's used. Quotas are per day and shared with every other session.
- The Keyword Tool and Bulk Keyword Tool share the search allowance. When eRank shows "You've Reached Your Search Quota", those tools are finished for the day. Close the dialog and work from the audits and the keyword store. Read eRank through its pages only, and leave upgrades to the seller.

Done when you've written down the audits and bulk lookups left today.

## 3. Audit the live listings

Audit each live listing at `https://members.erank.com/listing-audit/LISTING_ID`, one credit each. eRank can't audit drafts, so their tags get looked up in the store instead.

Issue `navigate`, two or three `wait` calls totalling about 25 seconds, and then `javascript_tool` with [extract_audit_rows.js](extract_audit_rows.js), as separate calls. Long `browser_batch` calls time out and lose their output. An empty result means the page is still drawing: wait and read it again. Reopening an audited listing costs no credit, so a lost read can be recovered free.

Append each output, unchanged, to `RUN/audits.txt`, then merge it:

```bash
seo_review.py ingest RUN
```

Done when `audits.txt` has 13 rows for every live listing.

## 4. Fill the gaps

Work out what each design could be found under, then price it. Write 1 to 3 buyer queries per design theme, ending in shirt, and look at what ranks:

```bash
seo_review.py niche RUN "krampus shirt" "bug christmas shirt" ...
```

It lists the tags top tees share, marks unpriced ones with `?`, and names the listings to audit to price the most tags. Then, cheapest source first:

1. The keyword store answers many terms for free. Treat a figure as current for 45 days.
2. The Bulk Keyword Tool prices 20 terms a run, and its daily allowance of 100 counts runs, not terms. Enter 20 comma-separated terms, press Analyze, wait about 10 seconds, run [extract_bulk_rows.js](extract_bulk_rows.js), and append its output to `audits.txt`. Reload the tool page before each run.
3. A competitor audit prices 13 tags for one credit, and eRank offers audits for this purpose. Skip picks whose tags are stuffed filler. Keep 3 credits spare.

Done when every theme has been priced and each listing has candidates, or you can say that its niche has none.

## 5. Check Etsy's own suggestions

Etsy's search autocomplete shows which exact phrases are live searches, at no eRank cost. It has no volume, so it sits beside eRank rather than replacing it. On 319 tags it confirmed 96% of terms eRank puts at 100+ searches and 11% of terms eRank measures at none.

```bash
seo_review.py suggest RUN seeds.txt
```

`seeds.txt` is optional: short theme words such as `krampus` or `bug shirt` for discovery, one per line. The command writes `RUN/suggest_batch.js` for every tag and seed not checked in the last 14 days, and prints how long it will take, about 9 seconds a term.

Open `https://www.etsy.com/` in a new tab, wait for it to load, and pass the batch file to `javascript_tool`. It returns at once and works through the list in the page. Keep that tab in front, because Chrome slows background tabs, and open nothing else in the meantime. Check on it occasionally:

```js
window.__ac.rows.length + ' of ' + window.__ac.total + ' stopped: ' + window.__ac.stopped + ' finished: ' + window.__ac.finished
```

A value in `stopped` means Etsy refused a request. Leave it stopped and tell the seller. Calls come only from this page, because a request from outside a browser gets a 403 from Etsy's bot protection, and the batch stays this slow because the endpoint isn't a supported API.

When it finishes, put the rows on the page, read them with `get_page_text`, and save them unchanged to `RUN/suggestions.txt`:

```js
var rows = window.__ac.rows; document.body.innerHTML = '<main><article><pre id="out"></pre></article></main>'; document.getElementById('out').textContent = rows.join('\n'); rows.length
```

For listings live for a few weeks, add related searches. Load the listing in a fresh tab, pacing as in `etsy-research`, run [extract_related_searches.js](extract_related_searches.js) and append its output to `RUN/related.txt`. A new listing has none. Related terms show the cluster Etsy places a listing in, so read them for drift from the design as well as for ideas.

```bash
seo_review.py ingest-suggestions RUN
seo_review.py signals RUN
seo_review.py discover RUN
```

`signals` compares autocomplete with eRank and lists wording fixes. `discover` writes `RUN/candidates.txt`, the unpriced phrases a tee shop could use. Pick the ones that fit a design and price them through step 4.

Read a **confirmed** term as a live search, with volume and competition still unknown: `funny christmas tee` is confirmed with under 20 searches and 372,788 tees. Read an unconfirmed term as probably dead only when eRank agrees. Autocomplete has gaps, since `devops shirt` is unconfirmed yet shows in related searches, and the design's own phrase can be worth keeping when few tees compete. Results come from the seller's market and can differ by country.

Done when every tag and candidate has a confirmed or unconfirmed mark, and you've reviewed the wording fixes.

## 6. Timing, for seasonal scopes

Seasonal terms have an annual average that hides the season, so compare the store's peak month with today. For a multi-year view, open Google Trends Explore for up to 5 terms over 5 years, wait about 30 seconds for the chart, and read the yearly peaks from a screenshot. Report them as rough figures. Leave its cookie banner alone.

## 7. Score

```bash
seo_review.py competition RUN candidates.txt
seo_review.py score RUN
seo_review.py score RUN candidates.txt
```

`candidates.txt` holds one term per line. The first `score` shows every current tag, and the second ranks the candidates.

## 8. Draft the plan

Write `RUN/plan.json`, keyed by listing ID:

```json
{"4610567904": {"short": "Prod To Stay Up", "title": "New title or null", "why": "Reason and expected gain", "swaps": [["old tag", "new tag", "Extra reason or empty", null]]}}
```

The last swap field is `"check"` for a Your call item, `"risk"` for an IP risk item, or null. The report writes the numeric reason and expected gain itself, so a note adds only what the numbers can't say.

Tags:

- Prefer sweet, then small. Busy needs an exact fit with the design. Keep open tags that are the design's own words.
- Between two similar terms, prefer the confirmed one. Replace a tag first when it's unconfirmed and eRank has it under 20 or at nothing, and apply the wording fixes from `signals`.
- A crowded term replaces a tag only if it clearly beats it. Flag it `check`.
- Use eRank's exact wording. Shoppers type shirt rather than tee, and one word or a plural can move a term from under 20 searches to hundreds.
- Read each brief to the end for the joke and the audience it names, and tag for that audience. A pun's literal subject isn't its buyer: Canary Deployment shows a bird, but it's a CI/CD joke for DevOps engineers, so `bird nerd shirt` is the wrong audience whatever its volume.
- Each new tag must be true of the design. Flag a loose fit, or a term for a product the shop doesn't sell, as `check`.
- Swap a tag only when the evidence favours it. Fixed designs only, since the shop doesn't sell personalised ones.

Titles:

- Lead with the strongest term that fits, then the design's own phrase, then audience or gift terms, ending in `Comfort Colors® 1717`. Stay within 140 characters.
- Phrases over 20 characters can't be tags, so the title is the only place for them.
- A seller approves a title whole, so uncertain terms belong in tags, where each gets its own decision.
- Set `title` to null when the current one is already right, and say why.

Brand and film references are the seller's call. They've chosen to keep terms like Home Alone and Linkin Park, so score those like any other term and leave them in place.

Done when this passes with no problems:

```bash
seo_review.py check RUN
```

## 9. Build and publish the report

Write `RUN/copy.json` with these fields as HTML strings:

- `title`: a short page name.
- `heading`, `meta`, `lede`.
- `findings`: `<li>` items on what the data shows, each with its numbers.
- `notes`: `<li>` items on where the numbers came from and their limits. Name any tool that was out of quota and what replaced it, the date of store figures, and which terms have no data.
- `other`: `<li>` items on work beyond tags and titles, publishing drafts first.

Run the copy past the `unslop` skill, then build:

```bash
seo_review.py report RUN
```

Publish `RUN/report.html` with the Artifact tool, declaring `capabilities: {"db": {}, "user": {}}`, and check the `decisions` collection with one probe write, read and delete. Give the seller the link, the headline findings and anything flagged, then stop. Their review comes next.

## 10. Apply the decisions

When the seller says they've finished, save the decisions and resolve them:

```
ArtifactData action=list, url=REPORT, collection=decisions, query={"limit": 1000}, out_dir=RUN/dec
```

```bash
seo_review.py resolve RUN RUN_FOLDER/dec/decisions
```

`RUN_FOLDER` is the run's full path, since `resolve` takes a real folder. This writes `changes.json` and lists every rejected and undecided item, which keep their current value.

Each description lead must repeat the listing's two **lead terms**, the first two comma-separated phrases of its final title, word for word within the first 160 characters. `changes.json` gives them as `terms`. Write `RUN/leads.json` as `{"listing-folder": "New lead"}`, keeping the design's real details and the audience from the current lead. Describe only what the design shows.

```bash
seo_review.py write RUN
seo_review.py write RUN --write
```

The first is a dry run. Fix any problems it lists before the second, which backs up each file, edits it through `ListingDocuments` and verifies it.

Done when every approved change is in `listing.yaml`, and the seller has heard which items stayed and why. Etsy still shows the old text at this point. Running `etsy-listings plan` and `apply` is a separate step that needs the seller's go-ahead.

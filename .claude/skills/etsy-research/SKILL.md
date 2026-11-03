---
name: etsy-research
description: Research the Etsy marketplace for Naturally Inked Studio. Covers competitor listings, shops, reviews, trends and mockups, plus the user's own shop and drafts. Queries the Etsy Open API v3 with the shop's credentials from the iCloud Drive workspace, and drives the user's Chrome (Claude in Chrome) for what only etsy.com shows, such as Star Seller, Bestseller and Popular-now filters and badges. Use when a task mentions the Etsy API, Etsy research, or querying Etsy listings, or needs live Etsy data.
---

# Etsy research

Two sources, each for what only it can do:

- **The Etsy Open API** (`etsy_api.py`) returns full listing, shop, image and review data. It has no Star Seller, Bestseller or Popular-now flag, and its search returns only the first page.
- **etsy.com search in the user's Chrome**, through the Claude in Chrome tools (`mcp__claude-in-chrome__*`). It has the Star Seller and Bestseller filters and the badges on each result card.

Research that needs those labels starts in the browser to build the listing set, then fills in each listing's details from the API. Research that doesn't need them uses the API alone.

## Star Seller and Bestseller research

1. **Load the Chrome tools** with one ToolSearch call: `tabs_context_mcp`, `tabs_create_mcp`, `navigate`, `javascript_tool`, `tabs_close_mcp`. If ToolSearch finds none, the session was started without `--chrome`. Say so and stop. Don't fall back to Playwright or another scripted browser: Etsy's bot protection blocks them, even after a person passes its slider.
2. **Open a search URL in a new tab.** Build it from these query parameters:
   - `q=christmas+tee`: the keywords.
   - `is_star_seller=true`: Star Seller shops only.
   - `attr_4=35`: the Christmas holiday attribute (other holidays have other values; read them off the URL after picking one in Etsy's filter panel).
   - `explicit=1`: Etsy adds it when filters are picked in its panel; keep it.
   - `page=N`: results page, about 60 listings each.
   - `order=date_desc` for newest first. Omit `order` for relevance, which favours listings that already sell and is usually what research wants.
   - Base: `https://www.etsy.com/search?…`.
3. **Extract the cards.** Pass the contents of [extract_search_cards.js](extract_search_cards.js) as the `text` of `javascript_tool`. It returns JSON with `listing_id`, `shop_id`, `position`, `ad` and `badges` (`Bestseller`, `Popular now`, `Etsy's Pick`) for each card in the main results grid, leaving out recommendation carousels. Append each page's rows to a JSONL file in the scratchpad, along with the URL.
4. **Keep the pace human.** The user's Chrome is signed in to their seller account, so a flag for automated traffic would land on the shop. Wait a few seconds between pages, keep to a handful of pages per search (around 20 page loads in a session), and stop if Etsy shows a verification check: tell the user rather than solving it. Close the tab when done.
5. **Fill in from the API.** `listings/batch listing_ids=…` (up to 100 IDs per call, `includes=Images,Shop`) for titles, tags, favourites, taxonomy and full-size image URLs (`url_fullxfull`); `shops/SHOP_ID` for review average, review count and sales.
6. **Filter out off-topic hits.** Etsy's filters are loose: a Christmas + Star Seller search still returns band tees and quilts. Drop them by title, tags or `taxonomy_id` before analysis.

## Etsy API

Every API query goes through `etsy_api.py` beside this file. It imports this repo's `etsy_listings` package, so the project's own transport supplies the app key, paces against Etsy's rate limit, retries 429s, and refreshes the OAuth token safely. Etsy rotates the refresh token on every refresh and the project's token store is the only writer that records the rotation, so the script is the one route to the API; the credential files stay unread.

From the repo root, in Bash or PowerShell:

```bash
uv run python .claude/skills/etsy-research/etsy_api.py PATH [k=v ...] [--auth] [--all]
```

- **PATH**: a v3 path. `listings/active`, `application/listings/active` and `/v3/application/listings/active` are equivalent. `{shop_id}` becomes the user's shop (67961328, NaturallyInkedStudio) and `{user_id}` the signed-in seller.
- **k=v**: query parameters; repeat a key to send it twice.
- **--auth**: adds the shop owner's bearer. Required for private data (draft or inactive listings, receipts, shipping profiles); public endpoints run without it, which also leaves the token file untouched.
- **--all**: follows `limit`/`offset` until `count` is reached and returns `{count, results}`.

Output is the JSON body on stdout; pipe it into `python -c` or a file for analysis. An Etsy refusal exits 1 with Etsy's own message on stderr. A 403 naming a missing scope means the stored sign-in lacks it, and the user grants it by running `etsy-listings auth` in the workspace.

The script sends GET only, and the browser workflow only reads search pages. The shop is the user's live store, so research stays read-only.

### Common queries

| Need | PATH and params |
|---|---|
| Search the marketplace | `listings/active keywords="line art tee" sort_on=score limit=100` |
| One listing, with images/shop | `listings/LISTING_ID includes=Images,Shop` |
| Several listings at once | `listings/batch listing_ids=1,2,3 includes=Images,Shop` |
| A shop's profile | `shops/SHOP_ID` (or `shops shop_name=NAME` to find it) |
| A shop's active listings | `shops/SHOP_ID/listings/active --all` |
| A shop's reviews | `shops/SHOP_ID/reviews --all` |
| Own drafts | `shops/{shop_id}/listings state=draft --auth` |
| Category tree | `seller-taxonomy/nodes` |

Prices arrive as `{amount, divisor, currency_code}`: the value is `amount / divisor`.

### Search limits

`listings/active` refuses any `offset` past the first page (`400: Offset exceeds the maximum allowed`), with or without `--auth`, so `--all` fails there. To reach more listings, split one search into narrow slices, each with its own first page of up to 100: `min_price`/`max_price` bands (one dollar wide still holds tens of thousands of Christmas tees), `taxonomy_id`, or keyword variants.

Without the browser, approximate seller strength from the shop's `review_average`, `review_count` and `transaction_sold_count`, and listing traction from `num_favorers`.

### Finding endpoints

For any endpoint, parameter or response field this file leaves out, look it up in the **Etsy Open API** MCP tools (`search_etsy_api`, `get_endpoint`, `get_schema`; load them with ToolSearch). They carry the official reference, including which OAuth scope each endpoint needs.

### Other workspaces

`ETSY_API_WORKSPACE=<path>` points the script at another `etsy-listings` workspace. The default is `C:\Users\Admin\iCloudDrive\naturally-inked-studio-workspace`.

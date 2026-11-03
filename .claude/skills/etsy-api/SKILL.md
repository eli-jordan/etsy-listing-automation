---
name: etsy-api
description: Query the Etsy Open API v3 programmatically with the Naturally Inked Studio credentials from the iCloud Drive workspace. Use when a task mentions the Etsy API, or needs live Etsy data: searching or querying listings, competitor shops, reviews, taxonomy, or the user's own shop and drafts.
---

# Etsy API

Every query goes through `etsy_api.py` beside this file. It imports this repo's `etsy_listings` package, so the project's own transport supplies the app key, paces against Etsy's rate limit, retries 429s, and refreshes the OAuth token safely. Etsy rotates the refresh token on every refresh and the project's token store is the only writer that records the rotation, so the script is the one route to Etsy; the credential files stay unread.

## Running a query

From the repo root, in Bash or PowerShell:

```bash
uv run python .claude/skills/etsy-api/etsy_api.py PATH [k=v ...] [--auth] [--all]
```

- **PATH**: a v3 path. `listings/active`, `application/listings/active` and `/v3/application/listings/active` are equivalent. `{shop_id}` becomes the user's shop (67961328, NaturallyInkedStudio) and `{user_id}` the signed-in seller.
- **k=v**: query parameters; repeat a key to send it twice.
- **--auth**: adds the shop owner's bearer. Required for private data (draft or inactive listings, receipts, shipping profiles); public endpoints run without it, which also leaves the token file untouched.
- **--all**: follows `limit`/`offset` until `count` is reached and returns `{count, results}`.

Output is the JSON body on stdout; pipe it into `python -c` or a file for analysis. An Etsy refusal exits 1 with Etsy's own message on stderr. A 403 naming a missing scope means the stored sign-in lacks it, and the user grants it by running `etsy-listings auth` in the workspace.

The script sends GET only. The shop is the user's live store, so research stays read-only.

## Common queries

| Need | PATH and params |
|---|---|
| Search the marketplace | `listings/active keywords="line art tee" sort_on=score limit=100` |
| One listing, with images/shop | `listings/LISTING_ID includes=Images,Shop` |
| Several listings at once | `listings/batch listing_ids=1,2,3` |
| A shop's profile | `shops/SHOP_ID` (or `shops shop_name=NAME` to find it) |
| A shop's active listings | `shops/SHOP_ID/listings/active --all` |
| A shop's reviews | `shops/SHOP_ID/reviews --all` |
| Own drafts | `shops/{shop_id}/listings state=draft --auth` |
| Category tree | `seller-taxonomy/nodes` |

Prices arrive as `{amount, divisor, currency_code}`: the value is `amount / divisor`.

## Marketplace search limits

- `listings/active` refuses any `offset` past the first page (`400: Offset exceeds the maximum allowed`), with or without `--auth`, so `--all` fails there. To reach more listings, split one search into narrow slices, each with its own first page of up to 100: `min_price`/`max_price` bands (one dollar wide still holds tens of thousands of Christmas tees), `taxonomy_id`, or keyword variants.
- The API has no Star Seller, Bestseller or Popular-now flag. Judge seller strength from the shop's `review_average`, `review_count` and `transaction_sold_count`, and listing traction from `num_favorers`. Scraping etsy.com search pages for the badges is blocked by Etsy's bot protection, even after a human passes its check, so don't try it.

## Finding endpoints

For any endpoint, parameter or response field this table leaves out, look it up in the **Etsy Open API** MCP tools (`search_etsy_api`, `get_endpoint`, `get_schema`; load them with ToolSearch). They carry the official reference, including which OAuth scope each endpoint needs.

## Other workspaces

`ETSY_API_WORKSPACE=<path>` points the script at another `etsy-listings` workspace. The default is `C:\Users\Admin\iCloudDrive\naturally-inked-studio-workspace`.

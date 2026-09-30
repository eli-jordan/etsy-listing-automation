# Reference

These documents describe conventions that a schema alone does not explain.
They are checked against current code, unlike the frozen project-wide plans.

| Topic | Reference |
|---|---|
| File roots, listing-local assets and reusable template assets | [Workspace references](workspace-references.md) |
| Which system writes each remote field | [Remote field ownership](field-ownership.md) |
| Price precedence, artwork selection and Etsy resource names | [Listing configuration rules](listing-configuration.md) |

Configuration shapes live beside their validators in `src/etsy_listings/core/config/`
and `src/etsy_listings/core/render/config.py`. API shapes are generated in
[`openapi.json`](../openapi.json). Consult those sources for exact fields
rather than copying the historical examples as a current schema.

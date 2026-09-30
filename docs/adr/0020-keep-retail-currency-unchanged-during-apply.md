# ADR-0020: Keep retail currency unchanged during apply

Send NOK retail prices to Printify verbatim as NOK minor units. Converting through a live FX rate during apply would change an unchanged listing and surrender control of the Etsy price; changing Printify billing currency cannot solve this. Printify's own profit display then compares unlike currencies and is not a usable margin calculation.

## Amendment

The numeric price-versus-production-cost refusal belongs to Publish. Documented `variants[].cost` exists only after the product is created, and Printify enforces the numeric comparison when publishing. Moving the refusal earlier would either miss first creation or make the engine depend on the undocumented wizard endpoint.

First recorded 2026-09-08 in [commit 869ab0e](https://github.com/eli-jordan/etsy-listing-automation/commit/869ab0e0e58dd438062de601b1ffd0fcde718ad0).

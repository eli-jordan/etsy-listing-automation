# ADR-0017: Refuse automated garment replacement

Status: accepted.

Once a Printify product exists, refuse changes to its blueprint or print provider and direct the seller to a new listing or manual changes. Live measurements found that Printify returns success while ignoring those update fields. Delete-and-recreate would sacrifice the connected Etsy listing's history merely to avoid re-entering a short configuration file.

First recorded 2026-09-08 in [commit 869ab0e](https://github.com/eli-jordan/etsy-listing-automation/commit/869ab0e0e58dd438062de601b1ffd0fcde718ad0).

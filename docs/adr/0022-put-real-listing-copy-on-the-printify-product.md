# ADR-0022: Put real listing copy on the Printify product

Send the listing's concrete title and composed description when creating or updating its Printify product; empty copy blocks deployment. Printify requires both, and real copy makes the product recognisable in its dashboard and supplies the duplicate-create match key. Selective publish still leaves title and description disabled, so Etsy remains their remote writer. A copy edit consequently also produces a Printify-stage diff.

First recorded 2026-09-08 in [commit fbdf6db](https://github.com/eli-jordan/etsy-listing-automation/commit/fbdf6dbf98b80b6c12fd65d661b612da2ce34e95).

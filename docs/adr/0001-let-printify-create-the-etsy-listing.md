# ADR-0001: Let Printify create the Etsy listing

Create the Etsy listing through Printify's native integration, then patch it through Etsy's API. Creating an independent Etsy draft would bypass the connection that routes orders to the printer. The Printify product's `external.id` is the bridge to the Etsy listing.

First recorded 2026-09-03 in [commit 086df20](https://github.com/eli-jordan/etsy-listing-automation/commit/086df2096d7b293ccbad394c9891b661a9a194b9).
